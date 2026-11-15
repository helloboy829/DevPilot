"""本地 QA 目录残留清单单测：仅固定文件名的元数据，不读内容。"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from devpilot.local_qa_residue import inventory_directory, main
from devpilot.local_qa_retention import main as retention_main

KNOWN = (
    "incomplete-output-disposal-complete.json",
    "incomplete-output-disposal-request.json",
    "observations.encrypted.jsonl",
    "observations.jsonl",
    "retention-receipt.json",
    "retention.lock",
    "run-receipt.json",
)


def run(*argv):
    output, error = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        code = main(list(argv))
    return code, output.getvalue(), error.getvalue()


class DirectoryResidueTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        if os.name == "posix":
            self.root.chmod(0o700)

    def tearDown(self):
        self.directory.cleanup()

    def test_reports_known_files_with_metadata_only(self):
        (self.root / "observations.jsonl").write_text(
            "SYNTHETIC_PLAINTEXT", encoding="utf-8"
        )
        (self.root / "run-receipt.json").write_bytes(b"{}")
        result = inventory_directory(self.root, confirm_metadata_only_inventory=True)
        self.assertEqual(result["schema"], "local-qa-directory-residue.v1")
        self.assertEqual(result["scope"], "metadata_only_known_names")
        self.assertEqual(result["content_status"], "not_inspected")
        self.assertEqual(result["verdict"], "NOT_EVALUATED")
        self.assertFalse(result["automatic_cleanup"])
        self.assertEqual(result["approval"], "not_approved")
        self.assertTrue(result["plaintext_copy_present"])
        self.assertFalse(result["encrypted_output_present"])
        by_name = {entry["name"]: entry for entry in result["entries"]}
        self.assertEqual(tuple(by_name), KNOWN)
        self.assertEqual(by_name["observations.jsonl"]["size"], 19)
        self.assertIsNone(by_name["observations.encrypted.jsonl"]["size"])
        self.assertFalse(by_name["observations.encrypted.jsonl"]["present"])
        self.assertNotIn("SYNTHETIC_PLAINTEXT", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_ignores_unknown_files_without_discovery(self):
        (self.root / "other.txt").write_text("SYNTHETIC_OTHER", encoding="utf-8")
        result = inventory_directory(self.root, confirm_metadata_only_inventory=True)
        self.assertEqual([entry["name"] for entry in result["entries"]], list(KNOWN))
        self.assertNotIn("other.txt", json.dumps(result))

    def test_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            inventory_directory(self.root, confirm_metadata_only_inventory=False)

    def test_rejects_non_directory(self):
        target = self.root / "target"
        target.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            inventory_directory(target, confirm_metadata_only_inventory=True)

    @unittest.skipUnless(os.name == "posix", "symlink creation is POSIX-specific")
    def test_rejects_symlinked_known_name(self):
        target = self.root / "target"
        target.write_text("{}", encoding="utf-8")
        (self.root / "run-receipt.json").symlink_to(target)
        with self.assertRaises(ValueError):
            inventory_directory(self.root, confirm_metadata_only_inventory=True)

    def test_retention_cli_exposes_residue_inventory(self):
        (self.root / "observations.jsonl").write_text("x", encoding="utf-8")
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = retention_main(
                [
                    "residue-inventory",
                    "--directory",
                    str(self.root),
                    "--confirm-metadata-only-directory-inventory",
                ]
            )
        self.assertEqual((code, error.getvalue()), (0, ""))
        result = json.loads(output.getvalue())
        self.assertEqual(result["schema"], "local-qa-directory-residue.v1")
        self.assertTrue(result["plaintext_copy_present"])

    def test_cli_outputs_projection_and_never_echoes_errors(self):
        code, output, error = run(
            "inventory",
            "--directory",
            str(self.root),
            "--confirm-metadata-only-directory-inventory",
        )
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output)["schema"], "local-qa-directory-residue.v1")
        code, output, error = run(
            "inventory",
            "--directory",
            str(self.root / "missing"),
            "--confirm-metadata-only-directory-inventory",
        )
        self.assertEqual(
            (code, output, error),
            (1, "", "Invalid residue inventory request\n"),
        )


if __name__ == "__main__":
    unittest.main()
