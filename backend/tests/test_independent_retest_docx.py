"""Pinned archived comparison projection; no source reads or recomputation."""

import base64
import copy
import io
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from markitdown import MarkItDown
from test_qa_report_docx import parts

from app.evaluation.independent_retest_docx import RENDERER_ID, render_independent_retest_docx
from app.evaluation.report_docx import ReportExportError

FIXTURE = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/synthetic-independent-retest-docx-v1.json"


def archive():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["document"]


def text(doc):
    return "\n".join(ET.fromstring(parts(render_independent_retest_docx(doc))["word/document.xml"]).itertext())


def test_real_package_bilingual_literal_all_cases_receipts_and_independent_reader():
    doc = archive()
    content = render_independent_retest_docx(doc)
    files = parts(content)
    assert RENDERER_ID == "independent-retest-docx-v1"
    assert set(files) == {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml", "word/_rels/document.xml.rels", "docProps/core.xml"}
    for xml in files.values():
        ET.fromstring(xml)
    result = text(doc)
    for value in ("NOT APPROVED", "草稿 / 未批准", "ALL frozen cases", doc["project_name"], doc["archive_hash"], doc["benchmark_hash"], RENDERER_ID):
        assert value in result
    for source in (doc["baseline"], doc["retest"]):
        for value in (source["run_id"], source["summary_hash"], source["plan_hash"], *map(str, source["assessment_ref"].values())):
            assert value in result
    for case in doc["cases"]:
        assert case["sample_id"] in result
        for side in ("baseline", "retest"):
            assert case[side + "_case_hash"] in result
            for task in case[side + "_tasks"]:
                assert task["task_id"] in result and task["resolution_hash"] in result
    opened = MarkItDown().convert_stream(io.BytesIO(content), file_extension=".docx").text_content
    # MarkItDown emits Markdown and escapes literal underscores; XML above remains exact.
    assert "fail_to_pass" in result
    assert "草稿 / 未批准" in opened and doc["archive_hash"] in opened and r"fail\_to\_pass" in opened
    assert doc["project_name"] in opened
    assert b"<img" not in files["word/document.xml"]
    for name, xml in files.items():
        if name.endswith(".rels"):
            assert all(r.get("TargetMode") is None and "://" not in r.get("Target", "") for r in ET.fromstring(xml))
        assert not any(s in name.lower() for s in ("macro", "vba", "embedding"))


def test_deterministic_fixture_no_mutation_no_new_metric_or_criteria_evaluation():
    doc = archive()
    original = copy.deepcopy(doc)
    content = render_independent_retest_docx(doc)
    assert content == base64.b64decode(json.loads(FIXTURE.read_text())["docx_base64"])
    assert content == render_independent_retest_docx(doc) and doc == original
    # Preserve stored values, do not recalculate floats/threshold status from counts.
    doc["pass_rate_delta"]["value"] = 0.12345
    doc["retest"]["human_pass_rate"]["value"] = 0.98765
    doc["retest"]["criteria_evaluation"]["status"] = "not_met"
    result = text(doc)
    assert "0.12345" in result and "0.98765" in result and "not_met" in result


def test_allowlist_excludes_unknown_sensitive_fields_at_every_projection_level():
    doc = archive()
    content = render_independent_retest_docx(doc)
    for value in (doc, doc["benchmark"], doc["baseline"], doc["baseline"]["counts"], doc["baseline"]["assessment_ref"], doc["cases"][0], doc["cases"][0]["baseline_tasks"][0]):
        value["output"] = "SYNTHETIC_PRIVATE_OUTPUT_GOLD_NOTE_KEY"
    doc["baseline"]["cases"][0]["tasks"][0]["output"] = "SYNTHETIC_PRIVATE_OUTPUT_GOLD_NOTE_KEY"
    assert render_independent_retest_docx(doc) == content
    doc["project_name"] = {"output": "SYNTHETIC_PRIVATE"}
    with pytest.raises(ReportExportError):
        render_independent_retest_docx(doc)


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema",), "qa-retest-archive.v1"),
        (("scope",), "same_benchmark_human_comparison"),
        (("acceptance",), "approved"),
        (("id",), "../private"),
        (("archive_hash",), "bad"),
        (("benchmark_hash",), "bad"),
        (("created_at_ms",), True),
        (("request_definition_changed",), 1),
        (("project_name",), "bad\x00"),
        (("project_name",), "bad\ud800"),
        pytest.param(("project_name",), "x" * 200_001, id="project-name-over-limit"),
        (("cases",), []),
        (("baseline", "readiness"), "provisional"),
        (("baseline", "policy"), {}),
        (("baseline", "blockers"), ["technical_incomplete"]),
        (("baseline", "acceptance"), "approved"),
        (("baseline", "run_status"), "interrupted"),
        (("baseline", "assessment_ref", "assessment_revision"), True),
        (("baseline", "assessment_ref", "assessment_hash"), "bad"),
        (("baseline", "counts", "unreviewed"), 1),
        (("baseline", "human_pass_rate", "denominator"), 1),
        (("baseline", "technical_counts", "other"), 1),
        (("baseline", "criteria_evaluation", "approval"), "approved"),
        (("pass_rate_delta", "denominator"), 1),
        (("pass_rate_delta", "value"), float("nan")),
        (("transitions", "fail_to_pass"), 0),
        (("benchmark", "preflight", "sample_count"), 1),
        (("benchmark", "limits", "mode"), "performance"),
        (("benchmark", "independent_policy"), {}),
    ],
)
def test_invalid_metadata_fails_closed_generic(path, value):
    doc = archive()
    current = doc
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(ReportExportError, match="^Archived comparison cannot be exported$"):
        render_independent_retest_docx(doc)


@pytest.mark.parametrize("field,value", [("ordinal", True), ("sample_id", "s1"), ("transition", "fail_to_fail"), ("baseline_decision", "pass"), ("baseline_case_hash", "0" * 64), ("baseline_tasks", [])])
def test_case_population_and_source_coherence_cannot_be_shortened_or_substituted(field, value):
    doc = archive()
    doc["cases"][1][field] = value
    with pytest.raises(ReportExportError):
        render_independent_retest_docx(doc)


def test_v1_sources_without_frozen_criteria_remain_exportable_without_defaulting_thresholds():
    doc = archive()
    del doc["benchmark"]["schema"], doc["benchmark"]["acceptance_criteria"]
    for side in ("baseline", "retest"):
        del doc[side]["criteria_evaluation"]
    result = text(doc)
    assert "criteria_evaluation" not in result and "min_pass_rate_bps" not in result
    assert "denominator" in result and "ALL frozen cases" in result


def test_package_limits_reject_whole_document_instead_of_truncating(monkeypatch):
    from app.evaluation import independent_retest_docx as renderer

    monkeypatch.setattr(renderer, "_document", lambda _: b"x" * 4_000_001)
    with pytest.raises(ReportExportError):
        render_independent_retest_docx(archive())


def test_all_500_frozen_cases_export_without_pagination_or_subset():
    doc = archive()
    for side in ("baseline", "retest"):
        source = doc[side]
        source["cases"] = [{**copy.deepcopy(source["cases"][0]), "ordinal": i} for i in range(1, 501)]
        source["counts"] = {"pass": 500, "fail": 0, "uncertain": 0, "unreviewed": 0}
        source["human_pass_rate"] = {"numerator": 500, "denominator": 500, "value": 1.0}
        source["technical_counts"] = {"collected": 500, "other": 0}
    template = doc["cases"][0]
    doc["cases"] = [{**copy.deepcopy(template), "ordinal": i, "sample_id": "synthetic-sample-" + str(i)} for i in range(1, 501)]
    doc["transitions"] = {"fail_to_pass": 0, "pass_to_fail": 0, "pass_to_pass": 500, "fail_to_fail": 0}
    doc["benchmark"]["preflight"].update(sample_count=500, request_count=500)
    doc["benchmark"]["limits"]["request_count"] = 500
    doc["pass_rate_delta"] = {"numerator": 0, "denominator": 500, "value": 0.0}
    result = text(doc)
    for i in range(1, 501):
        assert "synthetic-sample-" + str(i) in result
    doc["cases"].append(copy.deepcopy(doc["cases"][-1]))
    with pytest.raises(ReportExportError):
        render_independent_retest_docx(doc)
