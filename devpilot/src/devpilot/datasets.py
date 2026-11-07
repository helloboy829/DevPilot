"""Pure QA import/fingerprint primitives; independent from App, Harness and models."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

MAX_IMPORT_BYTES = 500_000
MAX_SAMPLES = 500


def normalized_question(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Invalid JSON constant")


def load_qa_rows(content: str, format: str) -> list[dict]:
    """Bounded strict JSON/JSONL; record-level schema validation is the caller's job."""
    try:
        if len(content.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise ValueError("Import too large")
        options = {"object_pairs_hook": _unique_pairs, "parse_constant": _reject_constant}
        if format == "json":
            rows = json.loads(content, **options)
        elif format == "jsonl":
            lines = [line for line in content.splitlines() if line.strip()]
            if len(lines) > MAX_SAMPLES:
                raise ValueError("Too many samples")
            rows = [json.loads(line, **options) for line in lines]
        else:
            raise ValueError("Unsupported import format")
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SAMPLES or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Invalid QA rows")
        return rows
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ValueError("Invalid QA document; check format, unique keys and size limits") from None


def dataset_fingerprint(source: dict, purpose: str, samples: list[dict]) -> str:
    snapshot = {"schema": "qa-dataset.v1", "source": source, "purpose": purpose, "samples": sorted(samples, key=lambda s: s["sample_id"])}
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
