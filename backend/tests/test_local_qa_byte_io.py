"""Local QA file bytes must round-trip on POSIX and the Windows CRT."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from devpilot import local_qa_output as output
from devpilot import local_qa_retention as retention
from devpilot.local_qa_cli import LocalRunManifest, _OutputStore, _write_run_receipt
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_templates import RequestTemplate


class LocalQAByteIOTest(unittest.TestCase):
    def test_windows_identity_uses_explicit_birthtime_across_stat_apis(self):
        values = dict(st_dev=1, st_ino=2, st_size=18, st_mtime_ns=100, st_birthtime_ns=50)
        original = SimpleNamespace(**values, st_ctime_ns=50)
        descriptor = SimpleNamespace(**values, st_ctime_ns=75)
        path = "synthetic-stat-only"
        with patch.object(retention.os, "name", "nt"), patch.object(retention.os, "fstat", return_value=descriptor), patch.object(retention.os, "lstat", return_value=original):
            retention._stable(path, 123, original)
            for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_birthtime_ns"):
                with self.subTest(field=field):
                    changed = SimpleNamespace(**{**vars(original), field: getattr(original, field) + 1})
                    with patch.object(retention.os, "fstat", return_value=changed):
                        with self.assertRaises(ValueError):
                            retention._stable(path, 123, original)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def private_file(self, name, raw):
        path = self.root / name
        path.write_bytes(raw)
        if os.name == "posix":
            path.chmod(0o600)
        return path

    def manifest(self):
        return LocalRunManifest(RequestTemplate("POST", "https://example.test:443", ()), QAJSONBinding("/q", "/a"), 1, 1, 1, 1000, 10000, 128, 4096, 129)

    def test_exclusive_writes_preserve_newlines_and_control_bytes(self):
        raw = b'{"synthetic":true}\n\r\n\x1aafter'
        for index, writer in enumerate((output._write_exclusive, retention._write_exclusive)):
            with self.subTest(writer=writer.__module__):
                path = self.root / f"receipt-{index}.json"
                writer(path, raw)
                self.assertEqual(path.read_bytes(), raw)

    def test_retention_json_reads_return_the_original_crlf_bytes(self):
        raw = b'{\r\n"synthetic":true\r\n}\r\n'
        path = self.private_file("receipt.json", raw)
        self.assertEqual(retention._read_json_bytes(path, 1024), ({"synthetic": True}, raw))

    def test_incomplete_output_hash_covers_all_raw_bytes(self):
        raw = b"synthetic\r\n\x1aafter\n"
        path = self.private_file("observations.encrypted.jsonl", raw)
        descriptor, info = retention._open_regular(path, 1024)
        try:
            self.assertEqual(retention._output_hash(self.root, descriptor, info, 1024), hashlib.sha256(raw).hexdigest())
        finally:
            os.close(descriptor)

    def test_encrypted_header_size_and_retention_receipt_match_disk_bytes(self):
        manifest = self.manifest()
        protection = output.LocalOutputProtection(base64.urlsafe_b64encode(b"x" * 32), retention_seconds=300)
        directory = self.root / "synthetic-output"
        store = output.EncryptedOutputStore(directory, str(uuid4()), manifest, protection)
        try:
            self.assertEqual((directory / output._FILE).stat().st_size, store.size)
            raw = (directory / "retention-receipt.json").read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), store.retention.receipt_sha256)
        finally:
            store.close()

    def test_plaintext_output_size_and_run_receipt_preserve_encoded_bytes(self):
        manifest = self.manifest()
        directory = self.root / "synthetic-plaintext"
        run_id = str(uuid4())
        store = _OutputStore(directory, run_id, manifest)
        try:
            store.append({"synthetic": "line\nvalue\u001aafter"})
            self.assertEqual(store.path.stat().st_size, store.size)
        finally:
            store.close()
        _write_run_receipt(directory, run_id, manifest)
        raw = (directory / "run-receipt.json").read_bytes()
        canonical = (json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        self.assertEqual(raw, canonical)


if __name__ == "__main__":
    unittest.main()
