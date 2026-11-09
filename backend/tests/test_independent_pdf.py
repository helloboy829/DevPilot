"""Pinned PDF projection: literal historical text, embedded font and bounded pages."""

import base64
import copy
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pypdfium2
import pytest
from pdfminer.high_level import extract_text, extract_text_to_fp
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1
from test_independent_report_docx import archive as report
from test_independent_retest_docx import archive as retest

from app.evaluation import independent_pdf as pdf
from app.evaluation.report_docx import ReportExportError

CASES = [(report, pdf.render_independent_report_pdf, pdf.REPORT_RENDERER_ID, "qa"), (retest, pdf.render_independent_retest_pdf, pdf.RETEST_RENDERER_ID, "retest")]


def compact(text):
    return "".join(text.split())


@pytest.mark.parametrize("factory,render,renderer,kind", CASES)
def test_real_pdf_independent_readers_all_historical_commitments_no_active_content(factory, render, renderer, kind):
    document = factory()
    original = copy.deepcopy(document)
    content = render(document)
    assert content.startswith(b"%PDF-1.4") and content.endswith(b"%%EOF\n")
    assert len(content) < pdf.MAX_PDF_BYTES and document == original
    text = compact(extract_text(io.BytesIO(content)))
    for value in [renderer, "NOT APPROVED", "草稿 / 未批准", document["archive_hash"], document["id"]]:
        assert compact(value) in text
    # Every literal text node in the pinned Word projection must survive PDF wrapping.
    import zipfile
    from xml.etree import ElementTree as ET

    source = pdf.render_independent_docx if kind == "qa" else pdf.render_independent_retest_docx
    with zipfile.ZipFile(io.BytesIO(source(document))) as package:
        root = ET.fromstring(package.read("word/document.xml"))
    # Default reader layout may interleave adjacent table cells by visual row.
    # Its raw painted-text order must retain every full source text node exactly.
    painted = io.StringIO()
    extract_text_to_fp(io.BytesIO(content), painted, laparams=None)
    painted = compact(painted.getvalue())
    for node in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
        assert compact(node.text or "") in painted
    if kind == "qa":
        for component in document["components"]:
            for value in component["assessment_ref"].values():
                assert str(value) in text
    else:
        assert document["benchmark_hash"] in text
        for case in document["cases"]:
            assert case["sample_id"] in text
            for side in ["baseline", "retest"]:
                assert case[side + "_case_hash"] in text
                for task in case[side + "_tasks"]:
                    assert task["task_id"] in text and task["resolution_hash"] in text
        for source in [document["baseline"], document["retest"]]:
            for value in source["assessment_ref"].values():
                assert str(value) in text
    with pypdfium2.PdfDocument(content) as reader:
        assert 1 <= len(reader) <= pdf.MAX_PAGES
        for index in range(len(reader)):
            page = reader[index]
            text_page = page.get_textpage()
            bitmap = page.render(scale=0.5)
            try:
                assert "NOT APPROVED" in text_page.get_text_range()
                for character in range(text_page.count_chars()):
                    left, bottom, right, top = text_page.get_charbox(character)
                    assert -1 <= left <= right <= pdf._WIDTH + 1
                    assert -1 <= bottom <= top <= pdf._HEIGHT + 1
                # Independent rasterizer must paint non-empty content, not only parse a header.
                assert bitmap.to_pil().convert("L").getextrema()[0] < 100
            finally:
                bitmap.close()
                text_page.close()
                page.close()
    parsed = PDFDocument(PDFParser(io.BytesIO(content)))
    assert not {"OpenAction", "AA", "AcroForm", "Names"} & parsed.catalog.keys()
    from pdfminer.pdfpage import PDFPage

    for page in PDFPage.create_pages(parsed):
        assert not page.annots
        for font in resolve1(page.resources["Font"]).values():
            value = resolve1(font)
            descriptor = resolve1(value["FontDescriptor"])
            assert "FontFile2" in descriptor and "ToUnicode" in value
    for private in ["SYNTHETIC_OUTPUT", "SYNTHETIC_GOLD", "SYNTHETIC_INDEPENDENT_NOTE", "encrypted_payload"]:
        assert private not in text


@pytest.mark.parametrize("factory,render,renderer,kind", CASES)
def test_deterministic_fixture_parallel_serialization_and_no_input_mutation(factory, render, renderer, kind):
    doc = factory()
    expected = render(doc)
    fixture = Path(__file__).resolve().parents[2] / f"frontend/tests/fixtures/synthetic-independent-{kind}-pdf-v1.json"
    assert expected == base64.b64decode(json.loads(fixture.read_text())["pdf_base64"])
    with ThreadPoolExecutor(max_workers=3) as workers:
        assert list(workers.map(render, [doc] * 6)) == [expected] * 6
    doc["output"] = "SYNTHETIC_PRIVATE_OUTPUT"
    assert render(doc) == expected


@pytest.mark.parametrize("text", ["\u0378", "\U0001f680", "e\u0301", "\u202eabc", "\u200d", "مرحبا", "\x01", "\ud800"])
def test_unsupported_glyph_direction_combining_or_controls_reject_whole_document(text):
    doc = report()
    doc["markdown"] = text
    with pytest.raises(ReportExportError, match="Archived draft cannot be exported"):
        pdf.render_independent_report_pdf(doc)


def test_literal_markup_long_receipts_newline_tab_and_long_table_rows_across_pages():
    doc = report()
    literal = "<script>alert(1)</script> [literal](https://invalid.example) **not active**"
    doc["markdown"] = literal + "\r\n汉字\tAB\rCD\n" + "x" * 1200 + "\n| ID | Text |\n| --- | --- |\n| sample-last | " + "汉" * 4000 + " END-LAST |"
    content = pdf.render_independent_report_pdf(doc)
    text = extract_text(io.BytesIO(content))
    assert compact(literal) in compact(text)
    assert "汉字    AB" in text and "CD" in text
    assert "x" * 1200 in compact(text) and "END-LAST" in compact(text)
    assert compact(text).count("汉") == 4001
    with pypdfium2.PdfDocument(content) as parsed:
        assert len(parsed) > 2


@pytest.mark.parametrize("field,value", [("schema", "qa-project-report-archive.v1"), ("archive_hash", "bad"), ("acceptance", "approved")])
@pytest.mark.parametrize("factory,render,renderer,kind", CASES)
def test_namespace_and_receipt_source_renderer_validation_not_bypassed(factory, render, renderer, kind, field, value):
    doc = factory()
    doc[field] = value
    with pytest.raises(ReportExportError):
        render(doc)


def test_font_and_engine_pins_fail_closed(monkeypatch, tmp_path):
    manifest = json.loads(pdf._FONT_PATH.with_suffix(".json").read_text())
    assert hashlib.sha256(pdf._FONT_PATH.read_bytes()).hexdigest() == manifest["sha256"] == pdf.FONT_SHA256
    assert manifest["character_count"] == 30890 and manifest["weight"] == 400
    assert "SIL OPEN FONT LICENSE Version 1.1" in pdf._FONT_PATH.with_name("OFL.txt").read_text()
    font = tmp_path / "unexpected.ttf"
    font.write_bytes(b"wrong font")
    with monkeypatch.context() as patch:
        patch.setattr(pdf, "_FONT_PATH", font)
        with pytest.raises(ReportExportError):
            pdf.render_independent_report_pdf(report())
    monkeypatch.setattr(pdf.reportlab, "Version", "future")
    with pytest.raises(ReportExportError):
        pdf.render_independent_report_pdf(report())


@pytest.mark.parametrize("limit,value", [("MAX_PAGES", 1), ("MAX_PDF_BYTES", 100)])
def test_page_and_final_byte_limits_never_truncate(limit, value, monkeypatch):
    monkeypatch.setattr(pdf, limit, value)
    with pytest.raises(ReportExportError):
        pdf.render_independent_retest_pdf(retest())


def test_engine_error_does_not_expose_internal_details(monkeypatch):
    def failed(*args, **kwargs):
        raise pdf.PDFError("SYNTHETIC_PRIVATE")

    monkeypatch.setattr(pdf, "Canvas", failed)
    with pytest.raises(ReportExportError) as raised:
        pdf.render_independent_report_pdf(report())
    assert "SYNTHETIC" not in str(raised.value)


def test_all_500_frozen_cases_and_final_task_commitments_survive_pagination():
    doc = retest()
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
    content = pdf.render_independent_retest_pdf(doc)
    result = compact(extract_text(io.BytesIO(content)))
    for i in range(1, 501):
        assert "synthetic-sample-" + str(i) in result
    assert doc["cases"][-1]["retest_tasks"][-1]["resolution_hash"] in result
    with pypdfium2.PdfDocument(content) as parsed:
        assert 2 < len(parsed) <= pdf.MAX_PAGES
    doc["cases"].append(copy.deepcopy(doc["cases"][-1]))
    with pytest.raises(ReportExportError):
        pdf.render_independent_retest_pdf(doc)
