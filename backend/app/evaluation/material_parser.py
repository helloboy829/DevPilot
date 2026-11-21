"""Bounded deterministic text extraction for uploaded evaluation materials."""

from __future__ import annotations

import csv
import json
import zipfile
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import PurePath
from typing import Literal
from xml.etree import ElementTree

MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 10_000
MAX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_BLOCKS = 20_000
MAX_TEXT_CHARS = 2_000_000
MAX_XLSX_CELLS = 1_000_000
MAX_XLSX_ROWS = 100_000


@dataclass(frozen=True)
class MaterialTextBlock:
    text: str
    source_location: dict[str, str | int]


@dataclass(frozen=True)
class MaterialParseResult:
    status: Literal["parsed", "blocked"]
    blocks: tuple[MaterialTextBlock, ...]
    reason: str | None = None


_BLOCKED = "File is damaged, encrypted, or unsupported"


class _ParseLimitExceeded(Exception):
    pass


class _BlockCollector:
    def __init__(self):
        self.blocks: list[MaterialTextBlock] = []
        self.text_chars = 0

    def add(self, text: str, source_location: dict[str, str | int]) -> None:
        self.text_chars += len(text)
        if len(self.blocks) >= MAX_BLOCKS or self.text_chars > MAX_TEXT_CHARS:
            raise _ParseLimitExceeded
        self.blocks.append(MaterialTextBlock(text, source_location))


def _result(blocks: list[MaterialTextBlock]) -> MaterialParseResult:
    if len(blocks) > MAX_BLOCKS or sum(len(block.text) for block in blocks) > MAX_TEXT_CHARS:
        raise _ParseLimitExceeded
    if not blocks:
        return MaterialParseResult("blocked", (), "No selectable text found; OCR is not configured")
    return MaterialParseResult("parsed", tuple(blocks))


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="strict")


def _parse_text(data: bytes) -> MaterialParseResult:
    text = _decode(data)
    collector = _BlockCollector()
    for index, line in enumerate(StringIO(text), 1):
        value = line.rstrip("\r\n")
        if value.strip():
            collector.add(value, {"line": index})
    return _result(collector.blocks)


def _parse_json(data: bytes) -> MaterialParseResult:
    value = json.loads(_decode(data))
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _result([MaterialTextBlock(text, {"json_pointer": ""})] if text else [])


def _parse_jsonl(data: bytes) -> MaterialParseResult:
    collector = _BlockCollector()
    for number, line in enumerate(StringIO(_decode(data)), 1):
        value_text = line.rstrip("\r\n")
        if value_text.strip():
            value = json.loads(value_text)
            collector.add(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")), {"line": number})
    return _result(collector.blocks)


def _parse_csv(data: bytes) -> MaterialParseResult:
    rows = csv.reader(StringIO(_decode(data), newline=""), strict=True)
    collector = _BlockCollector()
    for number, row in enumerate(rows, 1):
        if any(cell.strip() for cell in row):
            collector.add(json.dumps(row, ensure_ascii=False, separators=(",", ":")), {"row": number})
    return _result(collector.blocks)


def _check_archive(data: bytes) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(BytesIO(data))
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
        archive.close()
        raise _ParseLimitExceeded
    if any(item.flag_bits & 1 for item in entries):
        archive.close()
        raise ValueError("encrypted archive")
    return archive


def _parse_docx(data: bytes) -> MaterialParseResult:
    with _check_archive(data) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = root.find(f"{ns}body")
    if body is None:
        raise ValueError("missing document body")
    collector = _BlockCollector()
    paragraph_no = 0
    table_no = 0
    for child in body:
        if child.tag == f"{ns}p":
            paragraph_no += 1
            text = "".join(node.text or "" for node in child.iter(f"{ns}t"))
            if text.strip():
                collector.add(text, {"paragraph": paragraph_no})
        elif child.tag == f"{ns}tbl":
            table_no += 1
            for row_no, row in enumerate(child.findall(f"{ns}tr"), 1):
                cells = ["".join(node.text or "" for node in cell.iter(f"{ns}t")) for cell in row.findall(f"{ns}tc")]
                if any(cell.strip() for cell in cells):
                    collector.add(json.dumps(cells, ensure_ascii=False, separators=(",", ":")), {"table": table_no, "row": row_no})
    return _result(collector.blocks)


def _parse_xlsx(data: bytes) -> MaterialParseResult:
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.cell import range_boundaries

    with _check_archive(data):
        pass
    workbook = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
    try:
        collector = _BlockCollector()
        for sheet in workbook.worksheets:
            min_column, min_row, max_column, max_row = range_boundaries(sheet.calculate_dimension())
            row_count = max_row - min_row + 1
            column_count = max_column - min_column + 1
            if row_count > MAX_XLSX_ROWS or row_count * column_count > MAX_XLSX_CELLS:
                raise _ParseLimitExceeded

            visited_cells = 0
            for row_no, row in enumerate(sheet.iter_rows(values_only=True), 1):
                if row_no > MAX_XLSX_ROWS:
                    raise _ParseLimitExceeded
                visited_cells += len(row)
                if visited_cells > MAX_XLSX_CELLS:
                    raise _ParseLimitExceeded
                values = ["" if value is None else str(value) for value in row]
                while values and not values[-1].strip():
                    values.pop()
                if not any(value.strip() for value in values):
                    continue
                cell_range = f"A{row_no}:{get_column_letter(len(values))}{row_no}"
                collector.add(json.dumps(values, ensure_ascii=False, separators=(",", ":")), {"sheet": sheet.title, "row": row_no, "cell_range": cell_range})
        return _result(collector.blocks)
    finally:
        workbook.close()


def _parse_pdf(data: bytes) -> MaterialParseResult:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer

    collector = _BlockCollector()
    for page_no, page in enumerate(extract_pages(BytesIO(data)), 1):
        if page_no > 10_000:
            raise _ParseLimitExceeded
        block_no = 0
        for element in page:
            if isinstance(element, LTTextContainer):
                text = element.get_text().strip()
                if text:
                    block_no += 1
                    collector.add(text, {"page": page_no, "block": block_no})
    return _result(collector.blocks)


def parse_material(file_name: str, data: bytes, *, max_bytes: int = MAX_SOURCE_BYTES) -> MaterialParseResult:
    """Extract bounded text blocks; never execute document content or perform OCR."""
    if type(data) is not bytes or type(max_bytes) is not int or max_bytes < 1:
        return MaterialParseResult("blocked", (), _BLOCKED)
    if len(data) > min(max_bytes, MAX_SOURCE_BYTES):
        return MaterialParseResult("blocked", (), "File exceeds the parser size limit")
    suffix = PurePath(file_name).suffix.casefold()
    parser = {
        ".txt": _parse_text,
        ".md": _parse_text,
        ".json": _parse_json,
        ".jsonl": _parse_jsonl,
        ".csv": _parse_csv,
        ".docx": _parse_docx,
        ".xlsx": _parse_xlsx,
        ".pdf": _parse_pdf,
    }.get(suffix)
    if suffix in {".png", ".jpeg", ".jpg", ".webp"}:
        return MaterialParseResult("blocked", (), "Image OCR is not configured")
    if parser is None:
        return MaterialParseResult("blocked", (), _BLOCKED)
    try:
        return parser(data)
    except _ParseLimitExceeded:
        return MaterialParseResult("blocked", (), "Extracted content exceeds the parser limit")
    except Exception:
        return MaterialParseResult("blocked", (), _BLOCKED)
