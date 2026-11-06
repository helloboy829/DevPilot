"""report.py 纯逻辑单测（无网络）。"""

from __future__ import annotations

import unittest

from devpilot.toolkit.effect import EffectReport
from devpilot.toolkit.perf import PerfLevelResult, PerfReport
from devpilot.toolkit.report import build_component_test_report, build_run_summary


class TestBuildReport(unittest.TestCase):
    def _component(self):
        return {
            "id": "comp-1",
            "name": "测试组件",
            "transport": "dify_chat",
            "validation_type": "reference_text",
        }

    def test_component_report_contains_sections(self):
        effect = EffectReport(total=1, passed=1, overall="PASS")
        perf = PerfReport(overall="PASS", summary=PerfLevelResult(concurrency=10, success_rate=0.99))
        report = build_component_test_report(self._component(), test_type="effect", effect_report=effect, perf_report=perf)
        self.assertEqual(report["component"]["name"], "测试组件")
        self.assertEqual(report["test_type"], "effect")
        self.assertIn("effect", report)
        self.assertIn("perf", report)
        self.assertIn("params", report)
        self.assertEqual(report["assessment_version"], "component-test.i0.v1")

    def test_run_summary_overall_and_pass(self):
        effect = EffectReport(total=1, passed=1, overall="PASS")
        perf = PerfReport(overall="PASS", summary=PerfLevelResult(concurrency=10, success_rate=0.99))
        summary = build_run_summary(self._component(), test_type="perf", effect_report=effect, perf_report=perf)
        self.assertEqual(summary["overall"], "PASS")
        self.assertEqual(summary["effect"]["passed"], 1)
        self.assertEqual(summary["perf"]["concurrency"], 10)

    def test_run_summary_fail_when_any_fail(self):
        effect = EffectReport(total=1, failed=1, overall="FAIL")
        perf = PerfReport(overall="PASS", summary=PerfLevelResult(concurrency=10, success_rate=0.99))
        summary = build_run_summary(self._component(), test_type="perf", effect_report=effect, perf_report=perf)
        self.assertEqual(summary["overall"], "FAIL")

    def test_missing_report_never_defaults_to_pass(self):
        for test_type in ("effect", "perf"):
            with self.subTest(test_type=test_type):
                summary = build_run_summary(self._component(), test_type=test_type)
                self.assertEqual(summary["overall"], "REVIEW")

    def test_wrong_report_type_is_not_evidence_for_requested_test(self):
        summary = build_run_summary(self._component(), test_type="effect", perf_report=PerfReport(overall="PASS"))
        self.assertEqual(summary["overall"], "REVIEW")

    def test_combined_review_is_not_relabelled_as_failure_or_pass(self):
        summary = build_run_summary(
            self._component(),
            test_type="effect",
            effect_report=EffectReport(total=2, passed=1, manual_review=1, overall="REVIEW"),
            perf_report=PerfReport(overall="PASS"),
        )
        self.assertEqual(summary["overall"], "REVIEW")

    def test_failure_takes_precedence_over_review(self):
        summary = build_run_summary(
            self._component(),
            test_type="effect",
            effect_report=EffectReport(total=1, manual_review=1, overall="REVIEW"),
            perf_report=PerfReport(overall="FAIL"),
        )
        self.assertEqual(summary["overall"], "FAIL")

    def test_compact_effect_summary_includes_primary_denominator_and_rate(self):
        effect = EffectReport(total=4, passed=1, error=1, manual_review=1, not_run=1, pass_rate=0.25, overall="FAIL")
        summary = build_run_summary(self._component(), test_type="effect", effect_report=effect)
        self.assertEqual(summary["assessment_version"], "component-test.i0.v1")
        self.assertEqual(summary["effect"]["total"], 4)
        self.assertEqual(summary["effect"]["pass_rate"], 0.25)
        self.assertEqual(summary["effect"]["not_run"], 1)
        self.assertEqual(summary["effect"]["error"], 1)


if __name__ == "__main__":
    unittest.main()
