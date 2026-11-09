"""Pinned bilingual projection of authenticated historical comparison facts.

Unlike report archives, retests have no stored Markdown/template. This renderer
projects allowlisted stored metadata only; it never reopens sources, recomputes
metrics/criteria or grants approval. New layout semantics require a new ID.
"""

from __future__ import annotations

import io
import json
import math
import re
import zipfile
from xml.etree import ElementTree as ET

# Frozen low-level OOXML primitives only; never the report document renderer.
from app.evaluation.independent_report_docx import _OFFICE, _TYPES, _W, _relationships, _styles, _text, _xml
from app.evaluation.report_docx import ReportExportError

RENDERER_ID = "independent-retest-docx-v1"
_POLICY = {"id": "independent-double-blind.v1", "population": "all_frozen_effectiveness_samples", "timing": "post_collection_assessment"}
_TRANSITIONS = ("fail_to_pass", "pass_to_fail", "pass_to_pass", "fail_to_fail")
_TASK_FIELDS = ("task_id", "subject_hash", "round", "task_revision", "status", "resolution_revision", "resolution_hash")


def _pick(value, keys):
    result = {key: value[key] for key in keys}
    for item in result.values():
        if type(item) not in (str, int, float, bool) or (isinstance(item, float) and not math.isfinite(item)):
            raise ValueError
        if isinstance(item, str) and len(_text(item).encode("utf-8")) > 200_000:
            raise ValueError
    return result


def _hash(value, length=64):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{" + str(length) + "}", value):
        raise ValueError


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError


def _rate(value, total, delta=False):
    _integer(value["numerator"], -total if delta else 0, total)
    if type(value["denominator"]) is not int or value["denominator"] != total or type(value["value"]) not in (int, float) or not math.isfinite(value["value"]) or not (-1 if delta else 0) <= value["value"] <= 1:
        raise ValueError
    return _pick(value, ("numerator", "denominator", "value"))


def _criteria(value):
    if value["scope"] != "effectiveness_threshold_only" or value["approval"] != "not_approved" or value["blockers"] != [] or value["status"] not in {"met", "not_met"}:
        raise ValueError
    return {**_pick(value, ("scope", "status", "approval")), "blockers": [], "criteria": _pick(value["criteria"], ("schema", "version_label", "min_pass_rate_bps"))}


def _benchmark(value):
    result = _pick(value, ("project_id", "component_id", "dataset_id", "dataset_revision", "dataset_hash", "dataset_purpose", "response_mode", "sample_order", "evaluation_policy"))
    for key, fields in {
        "binding": ("schema", "input_pointer", "output_pointer"),
        "limits": ("mode", "concurrency", "request_count", "timeout_ms", "wall_time_ms", "max_total_body_bytes"),
        "preflight": ("sample_count", "request_count", "total_body_bytes"),
        "run_response_budgets": ("max_response_bytes", "max_total_response_bytes", "lease_grace_ms"),
    }.items():
        result[key] = _pick(value[key], fields)
    if value["independent_policy"] != _POLICY:
        raise ValueError
    result["independent_policy"] = dict(_POLICY)
    if "acceptance_criteria" in value:
        if value["schema"] != "qa-json-plan.v2":
            raise ValueError
        result.update(schema=value["schema"], acceptance_criteria=_pick(value["acceptance_criteria"], ("schema", "version_label", "min_pass_rate_bps")))
    return result


def _projection(doc):
    if doc["schema"] != "qa-independent-retest-archive.v1" or doc["scope"] != "same_benchmark_independent_comparison" or doc["acceptance"] != "not_approved":
        raise ValueError
    _hash(doc["id"], 32)
    _hash(doc["archive_hash"])
    _hash(doc["benchmark_hash"])
    _integer(doc["created_at_ms"], 0, 2**53 - 1)
    if type(doc["request_definition_changed"]) is not bool or not isinstance(doc["cases"], list):
        raise ValueError
    total = len(doc["cases"])
    _integer(total, 1, 500)
    benchmark = _benchmark(doc["benchmark"])
    if (
        benchmark["project_id"] != doc["project_id"]
        or benchmark["component_id"] != doc["component_id"]
        or benchmark["limits"]["mode"] != "effectiveness"
        or benchmark["preflight"]["sample_count"] != total
        or benchmark["limits"]["request_count"] != total
    ):
        raise ValueError
    result = _pick(doc, ("id", "project_id", "project_name", "component_id", "component_name", "created_at_ms", "archive_hash", "benchmark_hash", "request_definition_changed", "acceptance"))
    result.update(benchmark=benchmark, pass_rate_delta=_rate(doc["pass_rate_delta"], total, delta=True))
    for side in ("baseline", "retest"):
        source = doc[side]
        if (
            source["schema"] != "qa-independent-assessment-preview.v1"
            or source["scope"] != "verified_independent_assessment_preview"
            or source["policy"] != _POLICY
            or source["readiness"] != "review_complete"
            or source["blockers"] != []
            or source["acceptance"] != "not_approved"
            or source["run_status"] != "recording_finished"
        ):
            raise ValueError
        if source["project_id"] != doc["project_id"] or source["component_id"] != doc["component_id"] or len(source["cases"]) != total:
            raise ValueError
        for key in ("summary_hash", "plan_hash"):
            _hash(source[key])
        _hash(source["run_id"], 32)
        ref = _pick(source["assessment_ref"], ("assessment_id", "assessment_revision", "assessment_hash"))
        _hash(ref["assessment_id"], 32)
        _hash(ref["assessment_hash"])
        _integer(ref["assessment_revision"], 1, 1000)
        counts = _pick(source["counts"], ("pass", "fail", "uncertain", "unreviewed"))
        for count in counts.values():
            _integer(count, 0, total)
        if counts["uncertain"] or counts["unreviewed"] or counts["pass"] + counts["fail"] != total or source["technical_counts"] != {"collected": total, "other": 0}:
            raise ValueError
        rate = _rate(source["human_pass_rate"], total)
        if rate["numerator"] != counts["pass"]:
            raise ValueError
        result[side] = {
            **_pick(source, ("run_id", "run_status", "summary_hash", "plan_id", "plan_hash", "plan_label", "readiness", "acceptance")),
            "assessment_ref": ref,
            "counts": counts,
            "technical_counts": {"collected": total, "other": 0},
            "human_pass_rate": rate,
        }
        if "criteria_evaluation" in source:
            result[side]["criteria_evaluation"] = _criteria(source["criteria_evaluation"])
    if doc["baseline"]["run_id"] == doc["retest"]["run_id"] or doc["baseline"]["assessment_ref"]["assessment_id"] == doc["retest"]["assessment_ref"]["assessment_id"]:
        raise ValueError
    result["cases"] = []
    observed = dict.fromkeys(_TRANSITIONS, 0)
    sample_ids = set()
    task_count = 0
    for index, case in enumerate(doc["cases"], 1):
        if type(case["ordinal"]) is not int or case["ordinal"] != index or not isinstance(case["sample_id"], str) or not case["sample_id"] or case["sample_id"] in sample_ids or case["transition"] not in observed:
            raise ValueError
        sample_ids.add(case["sample_id"])
        observed[case["transition"]] += 1
        item = _pick(case, ("ordinal", "sample_id", "transition"))
        for side in ("baseline", "retest"):
            frozen = doc[side]["cases"][index - 1]
            outcome = case[side + "_decision"]
            _hash(case[side + "_case_hash"])
            if outcome not in {"pass", "fail"} or frozen["ordinal"] != index or frozen["outcome"] != outcome or frozen["case_hash"] != case[side + "_case_hash"] or frozen["tasks"] != case[side + "_tasks"]:
                raise ValueError
            tasks = case[side + "_tasks"]
            if not isinstance(tasks, list) or not tasks:
                raise ValueError
            task_count += len(tasks)
            if task_count > 20_000:
                raise ValueError
            for task in tasks:
                _hash(task["task_id"], 32)
                _hash(task["subject_hash"])
                _hash(task["resolution_hash"])
                for key in ("round", "task_revision", "resolution_revision"):
                    _integer(task[key], 1, 2**31 - 1)
                if task["status"] != "resolved":
                    raise ValueError
            item.update({side + "_decision": outcome, side + "_case_hash": case[side + "_case_hash"], side + "_tasks": [_pick(task, _TASK_FIELDS) for task in tasks]})
        if case["transition"] != case["baseline_decision"] + "_to_" + case["retest_decision"]:
            raise ValueError
        result["cases"].append(item)
    if doc["transitions"] != observed or any(type(value) is not int for value in doc["transitions"].values()):
        raise ValueError
    for side in ("baseline", "retest"):
        if sum(case[side + "_decision"] == "pass" for case in doc["cases"]) != result[side]["counts"]["pass"]:
            raise ValueError
        criteria = result[side].get("criteria_evaluation")
        if (criteria is None) != ("acceptance_criteria" not in benchmark) or (criteria is not None and criteria["criteria"] != benchmark["acceptance_criteria"]):
            raise ValueError
    result["transitions"] = _pick(doc["transitions"], _TRANSITIONS)
    return result


def _paragraph(parent, text, style=None):
    paragraph = ET.SubElement(parent, "w:p")
    if style:
        ET.SubElement(ET.SubElement(paragraph, "w:pPr"), "w:pStyle", {"w:val": style})
    # Public labels/pointers are literal, not HTML/Markdown or URL relationships.
    ET.SubElement(ET.SubElement(paragraph, "w:r"), "w:t", {"xml:space": "preserve"}).text = _text(text)


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _document(doc):
    root = ET.Element("w:document", {"xmlns:w": _W})
    body = ET.SubElement(root, "w:body")
    _paragraph(body, "DRAFT / NOT APPROVED — 草稿 / 未批准", "DraftNotice")
    _paragraph(body, "Independent historical retest / 独立历史重测", "Title")
    _paragraph(body, "Stored comparison facts only; ALL frozen samples. Historical revisions, not current state or approval. / 仅存档比较事实；全部冻结样本。历史修订，不是当前状态或批准。")
    _paragraph(body, "Renderer / 格式版本: " + RENDERER_ID)
    _paragraph(body, "Receipt / 存档收据", "Heading1")
    for key, value in doc.items():
        if key not in {"baseline", "retest", "benchmark", "cases", "transitions", "pass_rate_delta"}:
            _paragraph(body, key + ": " + (value if isinstance(value, str) else _json(value)))
    for side, title in (("baseline", "Baseline / 基线"), ("retest", "Retest / 重测")):
        _paragraph(body, title, "Heading1")
        for key, value in doc[side].items():
            _paragraph(body, key + ": " + (value if isinstance(value, str) else _json(value)))
    for key, title in (("benchmark", "Frozen benchmark / 冻结基准"), ("transitions", "Stored transitions / 存档转变计数"), ("pass_rate_delta", "Stored pass-rate delta / 存档通过率差值")):
        _paragraph(body, title, "Heading1")
        _paragraph(body, _json(doc[key]))
    _paragraph(body, "ALL frozen cases / 全部冻结样本", "Heading1")
    for case in doc["cases"]:
        _paragraph(body, "Case / 样本 " + str(case["ordinal"]), "Heading1")
        for key, value in case.items():
            _paragraph(body, key + ": " + (value if isinstance(value, str) else _json(value)))
    _paragraph(body, "Hashes are integrity receipts, not external signatures. met/PASS/deltas are not approval. / 哈希是完整性收据，不是外部签章。达标、PASS、差值均不是批准。")
    section = ET.SubElement(body, "w:sectPr")
    ET.SubElement(section, "w:pgSz", {"w:w": "11906", "w:h": "16838"})
    ET.SubElement(section, "w:pgMar", {"w:top": "1134", "w:right": "1134", "w:bottom": "1134", "w:left": "1134"})
    return _xml(root)


def render_independent_retest_docx(document):
    """The caller authenticates the immutable archive/receipt before rendering."""
    try:
        doc = _projection(document)
        if len(_json(doc).encode("utf-8")) > 2_000_000:
            raise ValueError
        core = ET.Element("cp:coreProperties", {"xmlns:cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties", "xmlns:dc": "http://purl.org/dc/elements/1.1/"})
        ET.SubElement(core, "dc:title").text = "Independent historical retest / 独立历史重测"
        ET.SubElement(core, "dc:creator").text = "DevPilot"
        ET.SubElement(core, "dc:description").text = "Historical comparison draft. NOT APPROVED. " + RENDERER_ID
        types = ET.Element("Types", {"xmlns": _TYPES})
        ET.SubElement(types, "Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
        ET.SubElement(types, "Default", {"Extension": "xml", "ContentType": "application/xml"})
        for name, content in (
            ("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
            ("/word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
            ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        ):
            ET.SubElement(types, "Override", {"PartName": name, "ContentType": content})
        files = {
            "[Content_Types].xml": _xml(types),
            "_rels/.rels": _relationships([(_OFFICE + "officeDocument", "word/document.xml"), ("http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml")]),
            "word/document.xml": _document(doc),
            "word/styles.xml": _styles(),
            "word/_rels/document.xml.rels": _relationships([(_OFFICE + "styles", "styles.xml")]),
            "docProps/core.xml": _xml(core),
        }
        if sum(map(len, files.values())) > 4_000_000:
            raise ValueError
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for name, content in files.items():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type, info.create_system, info.external_attr = zipfile.ZIP_DEFLATED, 3, 0o600 << 16
                package.writestr(info, content)
        if len(result.getvalue()) > 524_288:
            raise ValueError
        return result.getvalue()
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError):
        raise ReportExportError("Archived comparison cannot be exported") from None
