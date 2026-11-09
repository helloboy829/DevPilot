"""Independent pinned exports: historical commitments only, no approval or source reads."""

import base64
import copy
import hashlib
import io
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from markitdown import MarkItDown
from test_qa_report_docx import parts

from app.evaluation.independent_report_docx import RENDERER_ID, render_independent_docx
from app.evaluation.report_docx import ReportExportError

FIXTURE = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/synthetic-independent-qa-docx-v1.json"


def archive():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["document"]


def test_real_bilingual_package_pinned_receipts_literal_text_and_independent_reader():
    doc = archive()
    data = render_independent_docx(doc)
    files = parts(data)
    assert RENDERER_ID == "independent-qa-docx-v1"
    for xml in files.values():
        ET.fromstring(xml)
    text = "\n".join(ET.fromstring(files["word/document.xml"]).itertext())
    for value in ["DRAFT / NOT APPROVED", "草稿 / 未批准", "1 / 2", "50.00%", doc["archive_hash"], doc["template_hash"], RENDERER_ID, hashlib.sha256(doc["markdown"].encode()).hexdigest()]:
        assert value in text
    for component in doc["components"]:
        for value in [component["run_id"], component["summary_hash"], *map(str, component["assessment_ref"].values())]:
            assert value in text
    assert "<img src=" in text and "https://invalid.example" in text
    opened = MarkItDown().convert_stream(io.BytesIO(data), file_extension=".docx").text_content
    assert "50.00%" in opened and "NOT APPROVED" in opened and "草稿" in opened
    for name, xml in files.items():
        if name.endswith(".rels"):
            assert all(r.get("TargetMode") is None and "://" not in r.get("Target", "") for r in ET.fromstring(xml))
        assert not any(s in name.lower() for s in ("macro", "embedding", "vba"))
    assert b"<img" not in files["word/document.xml"]


def test_deterministic_fixture_no_metric_recomputation_or_mutation():
    doc = archive()
    original = copy.deepcopy(doc)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = render_independent_docx(doc)
    assert result == base64.b64decode(fixture["docx_base64"])
    assert result == render_independent_docx(doc) and doc == original
    doc["components"][0]["human_pass_rate"]["value"] = 0
    doc["template"]["layout"]["heading"] = "NEW CURRENT TEMPLATE"
    assert render_independent_docx(doc) == result  # Stored Markdown, never regenerated facts/layouts.
    doc.update(output="SYNTHETIC_OUTPUT", expected="SYNTHETIC_GOLD", request_url="SYNTHETIC_URL")
    assert b"SYNTHETIC" not in b"".join(parts(render_independent_docx(doc)).values())


@pytest.mark.parametrize(
    "changes",
    [
        {"schema": "qa-project-report-archive.v1"},
        {"scope": "immutable_qa_report_draft"},
        {"acceptance": "approved"},
        {"revision": True},
        {"revision": 0},
        {"archive_hash": "bad"},
        {"template_hash": "bad"},
        {"id": "../private"},
        {"components": []},
        {"markdown": "bad\x00text"},
        {"markdown": "bad\ud800text"},
        {"markdown": "x" * 200_001},
        {"markdown": "\n" * 5001},
        {"markdown": "| A | B |\n| --- | --- |\n| one |"},
        {"template": {"id": "verified-qa-project-en", "version": "1.0.0", "language": "en"}},
    ],
)
def test_reject_wrong_namespace_unbounded_xml_or_unapproved_metadata(changes):
    with pytest.raises(ReportExportError, match="Archived draft cannot be exported"):
        render_independent_docx({**archive(), **changes})


@pytest.mark.parametrize("field,value", [("assessment_id", "bad"), ("assessment_revision", True), ("assessment_hash", "bad")])
def test_invalid_historical_reference_fails_closed(field, value):
    doc = archive()
    doc["components"][0]["assessment_ref"][field] = value
    with pytest.raises(ReportExportError):
        render_independent_docx(doc)


@pytest.mark.parametrize("field,value", [("readiness", "provisional"), ("acceptance", "approved"), ("policy", {}), ("blockers", ["missing"])])
def test_only_complete_independent_historical_sources(field, value):
    doc = archive()
    doc["components"][0][field] = value
    with pytest.raises(ReportExportError):
        render_independent_docx(doc)


def test_multiple_components_keep_separate_historical_receipts_without_pooled_metrics():
    doc = archive()
    second = copy.deepcopy(doc["components"][0])
    second.update(run_id="2" * 32, summary_hash="3" * 64)
    second["assessment_ref"] = {"assessment_id": "4" * 32, "assessment_revision": 7, "assessment_hash": "5" * 64}
    doc["components"].append(second)
    text = "\n".join(ET.fromstring(parts(render_independent_docx(doc))["word/document.xml"]).itertext())
    for source in doc["components"]:
        assert source["run_id"] in text and source["assessment_ref"]["assessment_hash"] in text
    assert "@7" in text
    assert "Pooled" not in text
