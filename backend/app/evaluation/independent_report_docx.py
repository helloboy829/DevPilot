"""Independent historical Word drafts, pinned separately from owner-review exports.

This intentionally frozen OOXML renderer does not alter qa-docx-v1. Only stored
Markdown and archived public receipt metadata are emitted. No source reopening,
template lookup, metric recomputation, active content, network or approval.
Changing these semantics requires a new independent renderer ID.
"""

from __future__ import annotations

import hashlib
import html
import io
import re
import zipfile
from xml.etree import ElementTree as ET

from app.evaluation.report_docx import ReportExportError

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
RENDERER_ID = "independent-qa-docx-v1"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"


def _xml(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _text(value):
    if not isinstance(value, str) or any(not (ord(char) in {9, 10, 13} or 0x20 <= ord(char) <= 0xD7FF or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF) for char in value):
        raise ReportExportError("Archived draft cannot be exported")
    return value


def _paragraph(parent, text, style=None, indent=False):
    paragraph = ET.SubElement(parent, "w:p")
    if style or indent:
        props = ET.SubElement(paragraph, "w:pPr")
        if style:
            ET.SubElement(props, "w:pStyle", {"w:val": style})
        if indent:
            ET.SubElement(props, "w:ind", {"w:left": "360"})
    run = ET.SubElement(paragraph, "w:r")
    ET.SubElement(run, "w:t", {"xml:space": "preserve"}).text = _text(html.unescape(text))


def _cells(line):
    if not line.startswith("|") or not line.endswith("|"):
        raise ReportExportError("Archived draft cannot be exported")
    cells = [cell.strip() for cell in line[1:-1].split("|")]
    if not 1 <= len(cells) <= 16:
        raise ReportExportError("Archived draft cannot be exported")
    return cells


def _table(parent, rows):
    table = ET.SubElement(parent, "w:tbl")
    props = ET.SubElement(table, "w:tblPr")
    ET.SubElement(props, "w:tblW", {"w:w": "9638", "w:type": "dxa"})
    borders = ET.SubElement(props, "w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        ET.SubElement(borders, "w:" + side, {"w:val": "single", "w:sz": "4", "w:color": "CBD5E1"})
    grid = ET.SubElement(table, "w:tblGrid")
    width = str(9638 // len(rows[0]))
    for _ in rows[0]:
        ET.SubElement(grid, "w:gridCol", {"w:w": width})
    for index, cells in enumerate(rows):
        if len(cells) != len(rows[0]):
            raise ReportExportError("Archived draft cannot be exported")
        row = ET.SubElement(table, "w:tr")
        if index == 0:
            ET.SubElement(ET.SubElement(row, "w:trPr"), "w:tblHeader")
        for value in cells:
            cell = ET.SubElement(row, "w:tc")
            ET.SubElement(ET.SubElement(cell, "w:tcPr"), "w:tcW", {"w:w": width, "w:type": "dxa"})
            _paragraph(cell, value, "TableHeader" if index == 0 else None)


def _document(doc):
    root = ET.Element("w:document", {"xmlns:w": _W})
    body = ET.SubElement(root, "w:body")
    _paragraph(body, "DRAFT / NOT APPROVED — 草稿 / 未批准", "DraftNotice")
    lines = doc["markdown"].splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if index + 1 < len(lines) and line.startswith("|") and re.fullmatch(r"\|(?:\s*:?-+:?\s*\|)+", lines[index + 1]):
            rows = [_cells(line)]
            if len(_cells(lines[index + 1])) != len(rows[0]):
                raise ReportExportError("Archived draft cannot be exported")
            index += 2
            while index < len(lines) and lines[index].startswith("|"):
                rows.append(_cells(lines[index]))
                index += 1
            _table(body, rows)
            continue
        if line.startswith("# "):
            _paragraph(body, line[2:], "Title")
        elif line.startswith("## "):
            _paragraph(body, line[3:], "Heading1")
        elif line.lstrip().startswith("- "):
            _paragraph(body, "• " + line.lstrip()[2:], indent=line.startswith(" "))
        else:
            _paragraph(body, line)
        index += 1
    _paragraph(body, "Archive receipt / 存档收据", "Heading1")
    for line in (
        "Archive: " + doc["id"],
        "Revision: " + str(doc["revision"]),
        "Template: " + doc["template"]["id"] + "@" + doc["template"]["version"],
        "Archive SHA256: " + doc["archive_hash"],
        "Frozen Markdown SHA256: " + hashlib.sha256(doc["markdown"].encode("utf-8")).hexdigest(),
        "Export renderer: " + RENDERER_ID,
    ):
        _paragraph(body, line)
    for line in (
        "Scope: " + doc["scope"],
        "Frozen template SHA256: " + doc["template_hash"],
        "Historical independent sources / 历史独立来源 (not current review state):",
    ):
        _paragraph(body, line)
    for source in doc["components"]:
        ref = source["assessment_ref"]
        for line in (
            "Run: " + source["run_id"],
            "Assessment: " + ref["assessment_id"] + "@" + str(ref["assessment_revision"]),
            "Assessment SHA256: " + ref["assessment_hash"],
            "Summary SHA256: " + source["summary_hash"],
        ):
            _paragraph(body, line)
    section = ET.SubElement(body, "w:sectPr")
    ET.SubElement(section, "w:pgSz", {"w:w": "11906", "w:h": "16838"})
    ET.SubElement(section, "w:pgMar", {"w:top": "1134", "w:right": "1134", "w:bottom": "1134", "w:left": "1134", "w:header": "708", "w:footer": "708", "w:gutter": "0"})
    return _xml(root)


def _relationships(items):
    root = ET.Element("Relationships", {"xmlns": _REL})
    for index, (kind, target) in enumerate(items, 1):
        ET.SubElement(root, "Relationship", {"Id": "rId" + str(index), "Type": kind, "Target": target})
    return _xml(root)


def _styles():
    root = ET.Element("w:styles", {"xmlns:w": _W})
    for name, size, color in [("Normal", "22", "1E293B"), ("Title", "36", "0F172A"), ("Heading1", "28", "0F172A"), ("TableHeader", "22", "0F172A"), ("DraftNotice", "24", "9F1239")]:
        style = ET.SubElement(root, "w:style", {"w:type": "paragraph", "w:styleId": name, **({"w:default": "1"} if name == "Normal" else {})})
        ET.SubElement(style, "w:name", {"w:val": name})
        props = ET.SubElement(style, "w:rPr")
        ET.SubElement(props, "w:rFonts", {"w:ascii": "Calibri", "w:hAnsi": "Calibri", "w:eastAsia": "Microsoft YaHei"})
        ET.SubElement(props, "w:sz", {"w:val": size})
        ET.SubElement(props, "w:color", {"w:val": color})
        if name != "Normal":
            ET.SubElement(props, "w:b")
    return _xml(root)


def _eligible(doc):
    if doc["schema"] != "qa-independent-project-report-archive.v1" or doc["scope"] != "immutable_independent_qa_report_draft":
        raise ValueError
    template = doc["template"]
    if template["language"] not in {"en", "zh"} or template["id"] != "independent-qa-project-" + template["language"] or template["version"] != "1.0.0":
        raise ValueError
    if not re.fullmatch(r"[0-9a-f]{64}", doc["template_hash"]) or len(_text(doc["title"])) > 160:
        raise ValueError
    sources = doc["components"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
        raise ValueError
    for source in sources:
        if (
            source["schema"] != "qa-independent-assessment-preview.v1"
            or source["scope"] != "verified_independent_assessment_preview"
            or source["policy"] != {"id": "independent-double-blind.v1", "population": "all_frozen_effectiveness_samples", "timing": "post_collection_assessment"}
            or source["readiness"] != "review_complete"
            or source["blockers"] != []
            or source["acceptance"] != "not_approved"
            or not re.fullmatch(r"[0-9a-f]{32}", source["run_id"])
            or not re.fullmatch(r"[0-9a-f]{64}", source["summary_hash"])
        ):
            raise ValueError
        ref = source["assessment_ref"]
        if (
            set(ref) != {"assessment_id", "assessment_revision", "assessment_hash"}
            or not re.fullmatch(r"[0-9a-f]{32}", ref["assessment_id"])
            or type(ref["assessment_revision"]) is not int
            or not 1 <= ref["assessment_revision"] <= 1000
            or not re.fullmatch(r"[0-9a-f]{64}", ref["assessment_hash"])
        ):
            raise ValueError


def render_independent_docx(doc):
    """Export already authenticated historical metadata, not a new assessment."""
    try:
        _eligible(doc)
        if doc["acceptance"] != "not_approved" or not re.fullmatch(r"[0-9a-f]{32}", doc["id"]) or type(doc["revision"]) is not int or not 1 <= doc["revision"] <= 1000 or not re.fullmatch(r"[0-9a-f]{64}", doc["archive_hash"]):
            raise ValueError
        markdown = _text(doc["markdown"])
        if len(markdown.encode("utf-8")) > 200_000 or len(markdown.splitlines()) > 5000:
            raise ValueError
        core = ET.Element("cp:coreProperties", {"xmlns:cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties", "xmlns:dc": "http://purl.org/dc/elements/1.1/"})
        ET.SubElement(core, "dc:title").text = _text(doc["title"])
        ET.SubElement(core, "dc:creator").text = "DevPilot"
        ET.SubElement(core, "dc:description").text = "Historical independent QA draft. NOT APPROVED. " + RENDERER_ID
        types = ET.Element("Types", {"xmlns": _TYPES})
        ET.SubElement(types, "Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
        ET.SubElement(types, "Default", {"Extension": "xml", "ContentType": "application/xml"})
        for name, content in [
            ("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
            ("/word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
            ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        ]:
            ET.SubElement(types, "Override", {"PartName": name, "ContentType": content})
        files = {
            "[Content_Types].xml": _xml(types),
            "_rels/.rels": _relationships([(_OFFICE + "officeDocument", "word/document.xml"), ("http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml")]),
            "word/document.xml": _document(doc),
            "word/styles.xml": _styles(),
            "word/_rels/document.xml.rels": _relationships([(_OFFICE + "styles", "styles.xml")]),
            "docProps/core.xml": _xml(core),
        }
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for name, content in files.items():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type, info.create_system, info.external_attr = zipfile.ZIP_DEFLATED, 3, 0o600 << 16
                package.writestr(info, content)
        content = result.getvalue()
        if len(content) > 524_288:
            raise ValueError
        return content
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError):
        raise ReportExportError("Archived draft cannot be exported") from None
