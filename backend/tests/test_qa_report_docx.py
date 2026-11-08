"""Synthetic OOXML exports of frozen Markdown, never current templates or metrics."""

import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from markitdown import MarkItDown

from app.evaluation.report_docx import DOCX_MIME, RENDERER_ID, ReportExportError, render_archived_docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def archive(**changes):
    return {
        "id": "a" * 32,
        "revision": 2,
        "title": "Synthetic draft",
        "acceptance": "not_approved",
        "archive_hash": "b" * 64,
        "template": {"id": "synthetic-zh", "version": "1.0.0"},
        "markdown": (
            "# 项目 QA — 草稿 / 未批准\n\n## Synthetic draft\n\n"
            "| 组件 | 计划 | 通过 / 全部 | 通过率 |\n| --- | --- | ---: | ---: |\n"
            "| A &#124; B | QA &amp; test | 1 / 2 | 50.00% |\n| C | QA | 2 / 2 | 100.00% |\n\n"
            '- A &#124; B\n  - Run: abc\n\n&lt;img src="https://example.test/x"&gt;\nTemplate: synthetic-zh@1.0.0'
        ),
        **changes,
    }


def parts(data):
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        assert package.testzip() is None
        return {name: package.read(name) for name in package.namelist()}


def test_valid_package_real_multi_component_table_unicode_and_draft():
    doc = archive()
    data = render_archived_docx(doc)
    files = parts(data)
    assert DOCX_MIME == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert RENDERER_ID == "qa-docx-v1"
    assert set(files) == {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml", "word/_rels/document.xml.rels", "docProps/core.xml"}
    for xml in files.values():
        ET.fromstring(xml)
    root = ET.fromstring(files["word/document.xml"])
    tables = root.findall(".//" + W + "tbl")
    assert len(tables) == 1
    rows = tables[0].findall(W + "tr")
    assert len(rows) == 3 and all(len(row.findall(W + "tc")) == 4 for row in rows)
    text = "\n".join(root.itertext())
    for value in ["项目 QA — 草稿 / 未批准", "A | B", "QA & test", "50.00%", "100.00%", "1 / 2", "2 / 2", "<img src=", doc["archive_hash"], "synthetic-zh@1.0.0", RENDERER_ID, hashlib.sha256(doc["markdown"].encode()).hexdigest()]:
        assert value in text
    assert root.find(".//" + W + "tblHeader") is not None
    assert root.find(".//" + W + "sectPr") is not None
    # Existing harness dependency independently reads OOXML; no new export dependency.
    opened = MarkItDown().convert_stream(io.BytesIO(data), file_extension=".docx").text_content
    for row in ["| 组件 | 计划 | 通过 / 全部 | 通过率 |", "1 / 2", "50.00%", "100.00%", "QA & test", "DRAFT / NOT APPROVED"]:
        assert row in opened


def test_deterministic_read_only_and_no_current_template_or_model():
    doc = archive()
    first = render_archived_docx(doc)
    assert first == render_archived_docx({**doc, "components": [{"human_pass_rate": {"value": 0}}], "template": {**doc["template"], "layout": {"heading": "NEW TEMPLATE MUST NOT REPLACE FROZEN TEXT"}}})
    assert render_archived_docx(doc) == first
    assert doc == archive()


def test_no_active_content_external_relationships_or_sensitive_source_fields():
    files = parts(render_archived_docx(archive(request_url="SYNTHETIC_URL", output="SYNTHETIC_OUTPUT", expected="SYNTHETIC_GOLD")))
    assert all(marker not in b"".join(files.values()) for marker in [b"SYNTHETIC_URL", b"SYNTHETIC_OUTPUT", b"SYNTHETIC_GOLD"])
    for name, data in files.items():
        if name.endswith(".rels"):
            for relationship in ET.fromstring(data):
                assert relationship.get("TargetMode") is None
                assert "://" not in relationship.attrib["Target"]
        assert "macro" not in name.lower() and "embedding" not in name.lower()
    assert b"<img" not in files["word/document.xml"]


@pytest.mark.parametrize("text", ["bad\x00text", "bad\x0btext", "bad\ud800text", "x" * 200_001, "| A | B |\n| --- | --- |\n| one |", "\n" * 5001], ids=["null", "xml-control", "surrogate", "byte-bound", "ragged-table", "line-bound"])
def test_invalid_or_unbounded_frozen_content_fails_without_echo(text):
    with pytest.raises(ReportExportError, match="Archived draft cannot be exported"):
        render_archived_docx(archive(markdown=text))


@pytest.mark.parametrize("changes", [{"acceptance": "approved"}, {"id": "bad/path"}, {"revision": True}, {"revision": 0}, {"archive_hash": "bad"}])
def test_rejects_invalid_receipt_metadata(changes):
    with pytest.raises(ReportExportError):
        render_archived_docx(archive(**changes))


def test_browser_fixture_contains_actual_renderer_output():
    fixture = json.loads((Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/synthetic-qa-docx-v1.json").read_text(encoding="utf8"))
    saved = base64.b64decode(fixture["docx_base64"], validate=True)
    # XML parts must match; compressed bytes may differ across zlib versions.
    assert parts(saved) == parts(render_archived_docx(fixture["document"]))
    assert "50.00%" in MarkItDown().convert_stream(io.BytesIO(saved), file_extension=".docx").text_content
