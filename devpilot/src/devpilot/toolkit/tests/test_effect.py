"""effect.py 纯逻辑单测（无网络、无 deerflow）。

覆盖：效果 schema 解析、阈值判定、PASS/FAIL、MANUAL_REVIEW 排除自动通过率。
"""

from __future__ import annotations

import unittest

from devpilot.toolkit.effect import (
    EffectJudgeResult,
    EffectSampleResult,
    EffectThresholds,
    _build_effect_report,
    parse_effect_judge_output,
)


class TestParseEffectJudgeOutput(unittest.TestCase):
    def test_clean_json(self):
        raw = '{"accuracy": 90, "completeness": 80, "structure": 70, "overall": 80, "report": "好"}'
        r = parse_effect_judge_output(raw)
        self.assertEqual(r.accuracy, 90.0)
        self.assertEqual(r.completeness, 80.0)
        self.assertEqual(r.report, "好")

    def test_json_in_fence_with_think(self):
        raw = '<think>推理中</think>\n```json\n{"accuracy": 60, "completeness": 50, "structure": 40, "overall": 50, "report": "r"}\n```'
        r = parse_effect_judge_output(raw)
        self.assertEqual(r.overall, 50.0)

    def test_missing_overall_filled_with_mean(self):
        raw = '{"accuracy": 90, "completeness": 60, "structure": 60, "report": "r"}'
        r = parse_effect_judge_output(raw)
        self.assertEqual(r.overall, 70.0)

    def test_garbage_returns_zero(self):
        r = parse_effect_judge_output("完全不是 JSON 的文本")
        self.assertEqual(r.overall, 0.0)
        self.assertIn("解析失败", r.report)


class TestEffectThresholds(unittest.TestCase):
    def test_parses_effect_block(self):
        t = EffectThresholds.from_criteria(
            {"effect": {"accuracy_min": 80, "completeness_min": 70, "overall_min": 75}}
        )
        self.assertEqual(t.accuracy_min, 80.0)
        self.assertEqual(t.completeness_min, 70.0)
        self.assertEqual(t.structure_min, 0.0)
        self.assertEqual(t.overall_min, 75.0)

    def test_missing_criteria_defaults_zero(self):
        t = EffectThresholds.from_criteria(None)
        self.assertEqual(t.accuracy_min, 0.0)


def _sample(status, judge=None):
    return EffectSampleResult(sample_index=0, validation_type="reference_text", status=status, judge=judge)


class TestBuildEffectReport(unittest.TestCase):
    def test_all_pass(self):
        judge = EffectJudgeResult(accuracy=90, completeness=80, structure=70, overall=80)
        report = _build_effect_report([_sample("passed", judge), _sample("passed", judge)])
        self.assertEqual(report.overall, "PASS")
        self.assertEqual(report.auto_total, 2)
        self.assertEqual(report.auto_pass_rate, 1.0)

    def test_manual_review_excluded_from_auto_rate(self):
        judge = EffectJudgeResult(accuracy=90, completeness=80, structure=70, overall=80)
        report = _build_effect_report(
            [
                _sample("passed", judge),
                EffectSampleResult(sample_index=1, validation_type="manual_review", status="manual_review"),
            ]
        )
        self.assertEqual(report.overall, "PASS")
        self.assertEqual(report.total, 2)
        self.assertEqual(report.manual_review, 1)
        self.assertEqual(report.auto_total, 1)
        self.assertEqual(report.auto_pass_rate, 1.0)

    def test_all_manual_review_is_review(self):
        report = _build_effect_report(
            [EffectSampleResult(sample_index=0, validation_type="manual_review", status="manual_review")]
        )
        self.assertEqual(report.overall, "REVIEW")
        self.assertEqual(report.auto_total, 0)

    def test_any_fail_is_fail(self):
        good = EffectJudgeResult(accuracy=90, completeness=80, structure=70, overall=80)
        bad = EffectJudgeResult(accuracy=10, completeness=10, structure=10, overall=10)
        report = _build_effect_report([_sample("passed", good), _sample("failed", bad)])
        self.assertEqual(report.overall, "FAIL")
        self.assertEqual(report.failed, 1)


if __name__ == "__main__":
    unittest.main()
