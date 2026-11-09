"""Reproduce the PDF-v1 static font from a fixed, separately downloaded source.

Build-only tool; never runs at gateway startup or downloads anything. Install
fonttools==4.61.0 in an isolated build environment, then supply the upstream
NotoSansSC-VF.ttf. The bundled license/provenance must travel with the output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SOURCE_SHA256 = "d68bafcb48a2707749396aa12bbbd833cb70401f3a9a689fd2902c7e0d295964"
UPSTREAM_COMMIT = "f8d157532fbfaeda587e826d4cd5b21a49186f7c"
FONTTOOLS_VERSION = "4.61.0"


def build(source: Path, destination: Path) -> dict:
    import fontTools
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    if fontTools.__version__ != FONTTOOLS_VERSION:
        raise ValueError("Use the pinned fonttools build version")
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unexpected upstream font bytes")
    font = TTFont(source, recalcTimestamp=False)
    instantiateVariableFont(font, {"wght": 400}, inplace=True, optimize=True)
    # Derivative family/PostScript names are distinct; preserve copyright/license.
    names = {1: "DevPilot Export Sans", 2: "Regular", 3: "DevPilotExportSans-Regular-2.004-pdf-v1", 4: "DevPilot Export Sans Regular", 6: "DevPilotExportSans-Regular", 16: "DevPilot Export Sans", 17: "Regular"}
    for record in font["name"].names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding())
    for tag in ("DSIG", "STAT"):
        if tag in font:
            del font[tag]
    destination.parent.mkdir(parents=True, exist_ok=True)
    font.save(destination, reorderTables=True)
    return {
        "schema": "independent-pdf-font.v1",
        "family": "DevPilot Export Sans",
        "file": destination.name,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "upstream_repository": "https://github.com/notofonts/noto-cjk",
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_path": "Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf",
        "upstream_sha256": SOURCE_SHA256,
        "upstream_version": "2.004",
        "license": "OFL-1.1",
        "build_fonttools": FONTTOOLS_VERSION,
        "weight": 400,
        "character_count": len(font.getBestCmap()),
        "build": "scripts/build_independent_pdf_font.py",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    manifest = build(args.source, args.destination)
    args.destination.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
