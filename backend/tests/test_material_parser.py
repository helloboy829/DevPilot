from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.evaluation.material_parser import parse_material


def test_text_parser_preserves_text_and_emits_line_locations():
    result = parse_material("notes.md", b"first line\nsecond line\n")

    assert result.status == "parsed"
    assert [(block.text, block.source_location) for block in result.blocks] == [
        ("first line", {"line": 1}),
        ("second line", {"line": 2}),
    ]


def test_jsonl_parser_keeps_each_record_and_line_number():
    result = parse_material("cases.jsonl", b'{"prompt":"a"}\n{"prompt":"b"}\n')

    assert result.status == "parsed"
    assert [(block.text, block.source_location) for block in result.blocks] == [
        ('{"prompt":"a"}', {"line": 1}),
        ('{"prompt":"b"}', {"line": 2}),
    ]


def test_csv_parser_preserves_rows_and_cell_locations():
    result = parse_material("cases.csv", b"prompt,expected\nhello,world\n")

    assert result.status == "parsed"
    assert [block.source_location for block in result.blocks] == [
        {"row": 1},
        {"row": 2},
    ]


def test_xlsx_parser_reports_sheet_and_cell_range():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Cases"
    sheet.append(["prompt", "expected"])
    sheet.append(["hello", "world"])
    data = BytesIO()
    workbook.save(data)

    result = parse_material("cases.xlsx", data.getvalue())

    assert result.status == "parsed"
    assert [block.source_location for block in result.blocks] == [
        {"sheet": "Cases", "row": 1, "cell_range": "A1:B1"},
        {"sheet": "Cases", "row": 2, "cell_range": "A2:B2"},
    ]


def test_xlsx_parser_rejects_oversized_declared_cell_range_before_iteration(monkeypatch):
    from openpyxl import Workbook
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet

    workbook = Workbook()
    workbook.active.append(["prompt"])
    data = BytesIO()
    workbook.save(data)
    iterated = False

    def unexpected_iteration(self, *args, **kwargs):
        nonlocal iterated
        iterated = True
        return iter(())

    monkeypatch.setattr(ReadOnlyWorksheet, "calculate_dimension", lambda self: "A1:XFD1048576")
    monkeypatch.setattr(ReadOnlyWorksheet, "iter_rows", unexpected_iteration)

    result = parse_material("wide.xlsx", data.getvalue())

    assert result.status == "blocked"
    assert result.reason == "Extracted content exceeds the parser limit"
    assert iterated is False


def test_docx_parser_reports_paragraph_locations():
    document_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>First</w:t></w:r></w:p>
      <w:p><w:r><w:t>Second</w:t></w:r></w:p></w:body>
    </w:document>"""
    data = BytesIO()
    with ZipFile(data, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)

    result = parse_material("source.docx", data.getvalue())

    assert result.status == "parsed"
    assert [(block.text, block.source_location) for block in result.blocks] == [
        ("First", {"paragraph": 1}),
        ("Second", {"paragraph": 2}),
    ]


def test_pdf_parser_reports_page_and_text_block_locations():
    from reportlab.pdfgen.canvas import Canvas

    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 720, "First page")
    canvas.showPage()
    canvas.drawString(72, 720, "Second page")
    canvas.save()

    result = parse_material("source.pdf", output.getvalue())

    assert result.status == "parsed"
    assert [(block.text, block.source_location["page"]) for block in result.blocks] == [
        ("First page", 1),
        ("Second page", 2),
    ]


def test_image_is_blocked_without_ocr_instead_of_claiming_empty_parse():
    result = parse_material("scan.png", b"not a real image")

    assert result.status == "blocked"
    assert result.blocks == ()
    assert result.reason == "Image OCR is not configured"


def test_malformed_and_encrypted_formats_are_blocked_without_parser_details():
    result = parse_material("broken.pdf", b"not a PDF")

    assert result.status == "blocked"
    assert result.blocks == ()
    assert result.reason == "File is damaged, encrypted, or unsupported"


def test_parser_rejects_oversized_source_before_format_processing():
    result = parse_material("large.txt", b"x" * 10, max_bytes=9)

    assert result.status == "blocked"
    assert result.blocks == ()
    assert result.reason == "File exceeds the parser size limit"


def test_malformed_json_does_not_return_partial_preview():
    result = parse_material("broken.jsonl", b'{"prompt":"ok"}\nnot-json\n')

    assert result.status == "blocked"
    assert result.blocks == ()
    assert result.reason == "File is damaged, encrypted, or unsupported"


def test_parser_stops_at_block_budget_without_returning_partial_content():
    result = parse_material("many-lines.txt", ("x\n" * 20_001).encode())

    assert result.status == "blocked"
    assert result.blocks == ()
    assert result.reason == "Extracted content exceeds the parser limit"
