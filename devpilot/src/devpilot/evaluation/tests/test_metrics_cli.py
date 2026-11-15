"""离线指标 CLI 单测：仅本地文件，零网络/模型调用。"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from devpilot.qa_metrics_cli import main

START = 1_800_000_000_000


def observation(**changes):
    values = {
        "mode": "streaming",
        "outcome": "collected",
        "started_at_ms": START,
        "first_content_at_ms": START + 120,
        "last_content_at_ms": START + 1_120,
        "finished_at_ms": START + 1_200,
        "content_units": 500,
        "content_unit": "chars",
    }
    values.update(changes)
    return values


def run(*argv):
    output, error = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        code = main(list(argv))
    return code, output.getvalue(), error.getvalue()


class MetricsCliTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def test_stream_projection_is_printed_and_never_approves(self):
        path = self.write("observation.json", observation())
        code, output, error = run("stream", "--observation", path)
        self.assertEqual((code, error), (0, ""))
        result = json.loads(output)
        self.assertEqual(result["schema"], "qa-stream-metrics.v1")
        self.assertEqual(
            result["ttft"], {"status": "available", "ms": 120, "reason": None}
        )
        self.assertEqual(result["approval"], "not_approved")

    def test_unavailable_metrics_stay_null(self):
        path = self.write(
            "observation.json",
            observation(
                outcome="technical_incomplete",
                first_content_at_ms=None,
                last_content_at_ms=None,
            ),
        )
        code, output, _ = run("stream", "--observation", path)
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertIsNone(result["ttft"]["ms"])
        self.assertEqual(result["ttft"]["status"], "unavailable")

    def test_calibration_uses_only_definitive_pairs(self):
        path = self.write(
            "pairs.json",
            [
                {"human": "pass", "judge": "pass"},
                {"human": "fail", "judge": "pass"},
                {"human": None, "judge": "pass"},
                {"human": "uncertain", "judge": "fail"},
            ],
        )
        code, output, _ = run("calibration", "--pairs", path)
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertEqual(result["agreement"]["denominator"], 2)
        self.assertEqual(result["agreement"]["numerator"], 1)
        self.assertEqual(result["approval"], "not_approved")

    def test_image_diff_honours_threshold(self):
        reference = self.write("reference.json", [[0, 10], [20, 30]])
        candidate = self.write("candidate.json", [[0, 12], [20, 30]])
        code, output, _ = run(
            "image-diff",
            "--reference",
            reference,
            "--candidate",
            candidate,
            "--threshold",
            "2",
        )
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertEqual(result["schema"], "qa-image-diff.v1")
        self.assertEqual(result["max_absolute_error"], 2)
        self.assertTrue(result["within_threshold"])
        self.assertEqual(result["approval"], "not_approved")

    def test_signoff_requirement_projection(self):
        path = self.write(
            "signoff.json",
            {
                "required_distinct_approvers": 2,
                "distinct_approved_approvers": 1,
                "latest_decision": "approved",
            },
        )
        code, output, _ = run("signoff", "--requirement", path)
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertEqual(result["schema"], "qa-signoff-requirement.v1")
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["blockers"], ["insufficient_approvers"])
        self.assertEqual(result["approval"], "not_approved")

    def test_signoff_requirement_undefined_policy_is_null(self):
        path = self.write(
            "signoff.json",
            {
                "required_distinct_approvers": None,
                "distinct_approved_approvers": 2,
                "latest_decision": "approved",
            },
        )
        code, output, _ = run("signoff", "--requirement", path)
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertIsNone(result["satisfied"])
        self.assertEqual(result["blockers"], ["multi_level_policy_not_defined"])

    def test_signoff_requirement_rejects_unknown_fields(self):
        path = self.write(
            "signoff.json",
            {
                "required_distinct_approvers": 1,
                "distinct_approved_approvers": 1,
                "latest_decision": "approved",
                "secret": "SENTINEL",
            },
        )
        code, output, error = run("signoff", "--requirement", path)
        self.assertEqual((code, output, error), (1, "", "Invalid metric input\n"))

    def test_rejects_missing_invalid_oversized_and_non_regular_files(self):
        invalid = self.root / "invalid.json"
        invalid.write_text("{", encoding="utf-8")
        oversized = self.root / "oversized.json"
        oversized.write_bytes(b" " * (1_048_576 + 1))
        for path in (str(self.root / "missing.json"), str(invalid), str(oversized)):
            code, output, error = run("stream", "--observation", path)
            self.assertEqual((code, output, error), (1, "", "Invalid metric input\n"))

    def test_rejects_unknown_fields_and_invalid_threshold(self):
        path = self.write("observation.json", {**observation(), "secret": "SENTINEL"})
        code, output, error = run("stream", "--observation", path)
        self.assertEqual((code, output, error), (1, "", "Invalid metric input\n"))
        reference = self.write("reference.json", [[0]])
        candidate = self.write("candidate.json", [[0]])
        code, _, _ = run(
            "image-diff",
            "--reference",
            reference,
            "--candidate",
            candidate,
            "--threshold",
            "256",
        )
        self.assertEqual(code, 1)

    @unittest.skipUnless(os.name == "posix", "symlink creation is POSIX-specific")
    def test_rejects_symlinked_input(self):
        target = self.write("observation.json", observation())
        link = self.root / "link.json"
        link.symlink_to(target)
        code, output, error = run("stream", "--observation", str(link))
        self.assertEqual((code, output, error), (1, "", "Invalid metric input\n"))

    def test_usage_errors_do_not_echo_arguments(self):
        code, output, error = run("unknown", "--observation", "SENTINEL")
        self.assertEqual((code, output, error), (1, "", "Invalid metric input\n"))


if __name__ == "__main__":
    unittest.main()
