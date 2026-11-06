"""effect.py 纯逻辑单测（无网络、无 deerflow）。

覆盖：效果 schema 解析、固定分母、待复核/错误/未执行、主通过率与辅助自动通过率。
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from devpilot.toolkit.effect import (
    EffectJudgeResult,
    EffectSampleResult,
    EffectThresholds,
    _build_effect_report,
    effect_eval,
    parse_effect_judge_output,
)
from devpilot.toolkit.transports import TransportResult


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
        t = EffectThresholds.from_criteria({"effect": {"accuracy_min": 80, "completeness_min": 70, "overall_min": 75}})
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

    def test_manual_review_blocks_acceptance_and_stays_in_primary_denominator(self):
        judge = EffectJudgeResult(accuracy=90, completeness=80, structure=70, overall=80)
        report = _build_effect_report(
            [
                _sample("passed", judge),
                EffectSampleResult(sample_index=1, validation_type="manual_review", status="manual_review"),
            ]
        )
        self.assertEqual(report.overall, "REVIEW")
        self.assertEqual(report.pass_rate, 0.5)
        self.assertEqual(report.total, 2)
        self.assertEqual(report.manual_review, 1)
        self.assertEqual(report.auto_total, 1)
        self.assertEqual(report.auto_pass_rate, 1.0)

    def test_all_manual_review_is_review(self):
        report = _build_effect_report([EffectSampleResult(sample_index=0, validation_type="manual_review", status="manual_review")])
        self.assertEqual(report.overall, "REVIEW")
        self.assertEqual(report.auto_total, 0)

    def test_any_fail_is_fail(self):
        good = EffectJudgeResult(accuracy=90, completeness=80, structure=70, overall=80)
        bad = EffectJudgeResult(accuracy=10, completeness=10, structure=10, overall=10)
        report = _build_effect_report([_sample("passed", good), _sample("failed", bad)])
        self.assertEqual(report.overall, "FAIL")
        self.assertEqual(report.failed, 1)


class TestEffectEvidence(unittest.IsolatedAsyncioTestCase):
    def test_empty_report_cannot_pass(self):
        report = _build_effect_report([])
        self.assertEqual(report.overall, "REVIEW")
        self.assertEqual(report.pass_rate, 0.0)

    def test_all_outcomes_stay_in_denominator(self):
        report = _build_effect_report([_sample("passed"), _sample("failed"), _sample("manual_review"), _sample("error"), _sample("not_run")])
        self.assertEqual(report.total, 5)
        self.assertEqual(report.pass_rate, 0.2)
        self.assertEqual(report.not_run, 1)
        self.assertEqual(report.error, 1)
        self.assertEqual(report.auto_total, 3)
        self.assertEqual(report.overall, "FAIL")
        data = report.to_dict()
        self.assertEqual(data["pass_rate"], 0.2)
        self.assertEqual(data["not_run"], 1)

    def test_only_unexecuted_samples_need_review(self):
        report = _build_effect_report([_sample("not_run")])
        self.assertEqual(report.overall, "REVIEW")
        self.assertEqual(report.not_run, 1)
        self.assertEqual(report.error, 0)

    async def test_manual_review_does_not_hide_transport_error(self):
        result = TransportResult(transport="http_post", success=False, text="", error="timeout")
        report = await effect_eval([result], validation_type="manual_review", samples=[{"reference_text": "expected"}])
        self.assertEqual(report.overall, "FAIL")
        self.assertEqual(report.error, 1)
        self.assertEqual(report.manual_review, 0)
        self.assertEqual(report.samples[0].error, "timeout")

    async def test_manual_review_preserves_reference(self):
        result = TransportResult(transport="http_post", success=True, text="actual")
        report = await effect_eval([result], validation_type="manual_review", samples=[{"reference_text": "expected"}])
        self.assertEqual(report.overall, "REVIEW")
        self.assertEqual(report.samples[0].reference_text, "expected")
        self.assertEqual(report.samples[0].output_text, "actual")

    async def test_missing_results_are_not_run_in_original_denominator(self):
        result = TransportResult(transport="http_post", success=True, text="actual")
        judge = EffectJudgeResult(accuracy=90, completeness=90, structure=90, overall=90)
        samples = [{"reference_text": "first"}, {"reference_text": "second"}, {"reference_text": "third"}]
        with patch("devpilot.toolkit.effect.judge_reference_text", new=AsyncMock(return_value=judge)):
            report = await effect_eval([result], validation_type="reference_text", samples=samples)
        self.assertEqual(report.total, 3)
        self.assertEqual(report.passed, 1)
        self.assertEqual(report.not_run, 2)
        self.assertAlmostEqual(report.pass_rate, 1 / 3)
        self.assertEqual(report.overall, "REVIEW")
        self.assertEqual([s.sample_index for s in report.samples], [0, 1, 2])
        self.assertEqual(report.samples[1].reference_text, "second")

    async def test_extra_results_cannot_silently_extend_frozen_dataset(self):
        result = TransportResult(transport="http_post", success=True, text="actual")
        for samples in ([], [{"reference_text": "only"}]):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                await effect_eval([result, result], validation_type="manual_review", samples=samples)

    async def test_legacy_omitted_samples_still_count_all_results(self):
        report = await effect_eval([TransportResult(transport="http_post", success=True, text="actual")], validation_type="manual_review")
        self.assertEqual(report.total, 1)
        self.assertEqual(report.manual_review, 1)
        self.assertEqual(report.overall, "REVIEW")


if __name__ == "__main__":
    unittest.main()
