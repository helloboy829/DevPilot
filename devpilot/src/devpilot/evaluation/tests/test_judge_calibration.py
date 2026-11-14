"""人工/裁判一致性纯核心单测（零依赖，unittest）。"""

from __future__ import annotations

import json
import unittest

from devpilot.qa_judge_calibration import compute_judge_calibration


def items(*pairs):
    return [{"human": human, "judge": judge} for human, judge in pairs]


class TestJudgeCalibration(unittest.TestCase):
    def test_agreement_uses_only_definitive_pairs(self):
        result = compute_judge_calibration(items(("pass", "pass"), ("fail", "fail"), ("pass", "fail"), (None, "pass"), ("pass", None), ("uncertain", "pass"), ("fail", "uncertain")))
        self.assertEqual(result["schema"], "qa-judge-calibration.v1")
        self.assertEqual(result["scope"], "technical_judge_calibration_only")
        self.assertEqual(result["approval"], "not_approved")
        self.assertEqual(result["counts"], {"total": 7, "both_definitive": 3, "human_missing": 1, "judge_missing": 1, "uncertain_excluded": 2})
        self.assertEqual(result["confusion"], {"pass_pass": 1, "pass_fail": 1, "fail_pass": 0, "fail_fail": 1})
        self.assertEqual(result["agreement"], {"status": "available", "numerator": 2, "denominator": 3, "value": 0.6667, "reason": None})
        json.dumps(result)

    def test_no_definitive_pairs_is_insufficient_not_zero(self):
        result = compute_judge_calibration(items((None, "pass"), ("pass", None), ("uncertain", "uncertain")))
        self.assertEqual(result["counts"]["both_definitive"], 0)
        self.assertEqual(result["agreement"], {"status": "insufficient", "numerator": None, "denominator": 0, "value": None, "reason": "no_definitive_pairs"})

    def test_empty_input_is_insufficient(self):
        result = compute_judge_calibration([])
        self.assertEqual(result["counts"], {"total": 0, "both_definitive": 0, "human_missing": 0, "judge_missing": 0, "uncertain_excluded": 0})
        self.assertEqual(result["agreement"]["status"], "insufficient")
        self.assertIsNone(result["agreement"]["value"])

    def test_missing_and_uncertain_are_never_counted_as_agreement(self):
        result = compute_judge_calibration(items(("pass", "uncertain"), ("uncertain", "fail")))
        self.assertEqual(result["counts"]["both_definitive"], 0)
        self.assertEqual(result["counts"]["uncertain_excluded"], 2)
        self.assertEqual(sum(result["confusion"].values()), 0)

    def test_malformed_inputs_fail_closed(self):
        cases = [
            {},
            "pass",
            [{"human": "pass"}],
            [{"human": "pass", "judge": "pass", "extra": 1}],
            [{"human": "maybe", "judge": "pass"}],
            [{"human": [], "judge": "pass"}],
            [{"human": "pass", "judge": {}}],
            [{"human": "pass", "judge": 1}],
            [{"human": True, "judge": "pass"}],
            [None],
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    compute_judge_calibration(case)

    def test_item_bound_is_enforced(self):
        with self.assertRaises(ValueError):
            compute_judge_calibration([{"human": "pass", "judge": "pass"}] * 10_001)


if __name__ == "__main__":
    unittest.main()
