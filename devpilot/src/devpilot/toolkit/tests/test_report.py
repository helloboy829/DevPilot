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
        report = build_component_test_report(
            self._component(), test_type="effect", effect_report=effect, perf_report=perf
        )
        self.assertEqual(report["component"]["name"], "测试组件")
        self.assertEqual(report["test_type"], "effect")
        self.assertIn("effect", report)
        self.assertIn("perf", report)
        self.assertIn("params", report)

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


if __name__ == "__main__":
    unittest.main()
