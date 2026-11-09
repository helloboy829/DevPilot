"""Pinned PDF drafts of authenticated independent historical archives.

Only the frozen Word-v1 public document projections are consumed. No HTML,
network, OS-font fallback, source reopening, metric recomputation or approval.
All layout/font/engine semantics are versioned; oversized/unsupported text is
rejected as a whole, never silently replaced or truncated.
"""

from __future__ import annotations

import hashlib
import io
import threading
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfdoc import PDFError
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.evaluation.independent_report_docx import render_independent_docx
from app.evaluation.independent_retest_docx import render_independent_retest_docx
from app.evaluation.report_docx import ReportExportError

REPORT_RENDERER_ID = "independent-qa-pdf-v1"
RETEST_RENDERER_ID = "independent-retest-pdf-v1"
PDF_MIME = "application/pdf"
MAX_PDF_BYTES = 8_388_608
MAX_PAGES = 512
_FONT_PATH = Path(__file__).with_name("export_fonts") / "independent_pdf_v1" / "DevPilotExportSans-Regular.ttf"
# Filled from the reproducible, checked-in static font; never read from a client.
FONT_SHA256 = "3c7dfdf896efce570073376a39654dd98d4776fa9ecdbc0fe01c68418b190762"
_FONT_NAME = "DevPilotExportSans-PDF-v1"
_LOCK = threading.Lock()
_FONT = None
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WIDTH, _HEIGHT = 595.276, 841.89
_MARGIN, _TOP, _BOTTOM = 43.0, 785.0, 49.0
_CONTENT = _WIDTH - 2 * _MARGIN


def _font():
    global _FONT
    data = _FONT_PATH.read_bytes()
    if reportlab.Version != "4.4.10" or hashlib.sha256(data).hexdigest() != FONT_SHA256:
        raise ValueError
    if _FONT is None:
        _FONT = TTFont(_FONT_NAME, io.BytesIO(data), validate=1)
        pdfmetrics.registerFont(_FONT)
    return _FONT


def _literal(text, font):
    if not isinstance(text, str):
        raise ValueError
    for char in text:
        if char in "\t\n\r":
            continue
        code = ord(char)
        if not font.face.charToGlyph.get(code) or unicodedata.combining(char) or unicodedata.category(char).startswith("C") or unicodedata.bidirectional(char) in {"R", "AL", "AN"}:
            raise ValueError
    # PDF-v1 defines tabs as four spaces and CRLF/CR as newline; no other changes.
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")


def _blocks(content, font):
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        if package.getinfo("word/document.xml").file_size > 4_000_000:
            raise ValueError
        root = ET.fromstring(package.read("word/document.xml"))
    body = root.find(_W + "body")
    if body is None:
        raise ValueError
    blocks = []
    size = 0
    for node in body:
        if node.tag == _W + "sectPr":
            continue
        if node.tag == _W + "p":
            value = _literal("".join(node.itertext()), font)
            style = node.find("./" + _W + "pPr/" + _W + "pStyle")
            style = style.get(_W + "val") if style is not None else None
            blocks.append((style or "Normal", value))
            size += len(value.encode("utf-8"))
        elif node.tag == _W + "tbl":
            rows = []
            for row in node.findall(_W + "tr"):
                cells = [_literal("".join(cell.itertext()), font) for cell in row.findall(_W + "tc")]
                if not cells or len(cells) > 16 or (rows and len(cells) != len(rows[0])):
                    raise ValueError
                size += sum(len(cell.encode("utf-8")) for cell in cells)
                rows.append(cells)
            if not rows:
                raise ValueError
            blocks.append(("Table", rows))
        else:
            raise ValueError
        if size > 2_000_000 or len(blocks) > 20_000:
            raise ValueError
    return blocks


def _wrap(text, width, font, size):
    # Linear glyph-advance wrapping also handles unbroken receipts/CJK. No HTML
    # parser or URL recognizer is involved, and no glyph may be substituted.
    lines, current, used = [], [], 0.0
    for char in text:
        advance = font.face.charWidths[ord(char)] * size / 1000 if char != "\n" else 0
        if advance > width:
            raise ValueError
        if char == "\n" or (current and used + advance > width):
            lines.append("".join(current))
            current, used = [], 0.0
        if char != "\n":
            current.append(char)
            used += advance
    lines.append("".join(current))
    return lines


class _BoundedBuffer(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_PDF_BYTES:
            raise ValueError
        return super().write(data)


class _Layout:
    def __init__(self, renderer, font):
        self.font, self.renderer = font, renderer
        self.buffer = _BoundedBuffer()
        self.canvas = Canvas(self.buffer, pagesize=(_WIDTH, _HEIGHT), pageCompression=1, invariant=1, pdfVersion=(1, 4), initialFontName=_FONT_NAME)
        self.canvas.setTitle("Independent historical draft / 独立历史草稿")
        self.canvas.setAuthor("DevPilot")
        self.canvas.setSubject(renderer + "; NOT APPROVED; pinned historical public projection")
        self.canvas.setCreator("DevPilot " + renderer)
        self.page, self.y = 0, _TOP
        self.new_page()

    def new_page(self):
        if self.page >= MAX_PAGES:
            raise ValueError
        if self.page:
            self.canvas.showPage()
        self.page += 1
        self.canvas.setFont(_FONT_NAME, 7)
        self.canvas.setFillColorRGB(0.32, 0.12, 0.12)
        self.canvas.drawString(_MARGIN, 811, "DRAFT / NOT APPROVED — 草稿 / 未批准")
        self.canvas.setFillColorRGB(0.25, 0.25, 0.25)
        self.canvas.drawString(_MARGIN, 28, self.renderer + " | historical draft / 历史草稿 | " + str(self.page))
        self.y = _TOP

    def paragraph(self, style, text):
        size = {"Title": 16, "Heading1": 12, "DraftNotice": 11}.get(style, 9)
        leading = size * 1.45
        for line in _wrap(text, _CONTENT, self.font, size):
            if self.y - leading < _BOTTOM:
                self.new_page()
            self.canvas.setFont(_FONT_NAME, size)
            self.canvas.setFillColorRGB(0.09, 0.12, 0.17)
            self.canvas.drawString(_MARGIN, self.y - size, line)
            self.y -= leading
        self.y -= 5

    def table(self, rows):
        size, leading, padding = 8.0, 12.0, 5.0
        cell_width = _CONTENT / len(rows[0])
        for row_index, row in enumerate(rows):
            wrapped = [_wrap(cell, cell_width - 2 * padding, self.font, size) for cell in row]
            offset, count = 0, max(map(len, wrapped))
            while offset < count:
                available = int((self.y - _BOTTOM - 2 * padding) // leading)
                if available < 1:
                    self.new_page()
                    continue
                take = min(count - offset, available)
                height = take * leading + 2 * padding
                for index, lines in enumerate(wrapped):
                    x = _MARGIN + index * cell_width
                    self.canvas.setStrokeColorRGB(0.65, 0.68, 0.72)
                    self.canvas.setFillColorRGB(*(0.94, 0.95, 0.97) if row_index == 0 else (1, 1, 1))
                    self.canvas.rect(x, self.y - height, cell_width, height, fill=1, stroke=1)
                    self.canvas.setFillColorRGB(0.09, 0.12, 0.17)
                    self.canvas.setFont(_FONT_NAME, size)
                    for line_index, line in enumerate(lines[offset : offset + take]):
                        self.canvas.drawString(x + padding, self.y - padding - size - line_index * leading, line)
                self.y -= height
                offset += take
        self.y -= 8

    def finish(self):
        self.canvas.save()
        return self.buffer.getvalue()


def _render(doc, source, renderer):
    try:
        # The source renderers validate their exact historical namespaces and
        # construct allowlisted document text. They never consult current state.
        content = source(doc)
        with _LOCK:  # ReportLab's shared dynamic TTFont subset state is serialized.
            font = _font()
            blocks = _blocks(content, font)
            layout = _Layout(renderer, font)
            layout.paragraph("Normal", "PDF renderer: " + renderer + " | embedded DevPilot Export Sans 2.004 / 固定嵌入字体")
            for style, value in blocks:
                if style == "Table":
                    layout.table(value)
                else:
                    layout.paragraph(style, value)
            return layout.finish()
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError, OSError, zipfile.BadZipFile, ET.ParseError, PDFError, ReportExportError):
        raise ReportExportError("Archived draft cannot be exported by this PDF renderer") from None


def render_independent_report_pdf(document):
    return _render(document, render_independent_docx, REPORT_RENDERER_ID)


def render_independent_retest_pdf(document):
    return _render(document, render_independent_retest_docx, RETEST_RENDERER_ID)
