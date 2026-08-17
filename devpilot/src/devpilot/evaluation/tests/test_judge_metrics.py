"""judge.py / metrics.py 纯逻辑单测（零依赖，unittest）。

运行（repo 根目录）：
    python -m unittest discover -s devpilot/evaluation/tests -v
"""

from __future__ import annotations

import unittest

from devpilot.evaluation.judge import (
    EvaluationResult,
    build_prompt,
    compute_overall,
    parse_judge_output,
    strip_think_blocks,
)
from devpilot.evaluation.metrics import aggregate


class TestEvaluationResult(unittest.TestCase):
    def test_clamps_scores_and_rate(self):
        r = EvaluationResult(
            task_score=150,
            code_score=-10,
            test_score=50,
            hallucination_rate=2.0,
            confidence=88,
            overall=95,
            report="x",
        )
        self.assertEqual(r.task_score, 100.0)
        self.assertEqual(r.code_score, 0.0)
        self.assertEqual(r.hallucination_rate, 1.0)

    def test_fill_overall_when_missing(self):
        r = EvaluationResult(
            task_score=80,
            code_score=90,
            test_score=70,
            hallucination_rate=0.0,
            confidence=100,
            overall=0.0,
        ).fill_overall()
        self.assertGreater(r.overall, 0.0)

    def test_to_dict_uses_camel_case(self):
        r = EvaluationResult(task_score=90, code_score=85, test_score=80,
                             hallucination_rate=0.03, confidence=88, overall=86, report="ok")
        d = r.to_dict()
        self.assertEqual(set(d.keys()), {
            "taskScore", "codeScore", "testScore", "hallucinationRate",
            "confidence", "overall", "report",
        })


class TestComputeOverall(unittest.TestCase):
    def test_perfect_scores(self):
        overall = compute_overall(100, 100, 100, 100, 0.0)
        self.assertEqual(overall, 100)

    def test_hallucination_penalty(self):
        clean = compute_overall(100, 100, 100, 100, 0.0)
        noisy = compute_overall(100, 100, 100, 100, 0.5)
        self.assertLess(noisy, clean)


class TestStripThinkBlocks(unittest.TestCase):
    def test_closed_block(self):
        self.assertEqual(strip_think_blocks("a<think>x</think>b"), "ab")

    def test_truncate_unclosed(self):
        text = "before<think>unfinished"
        self.assertEqual(strip_think_blocks(text, truncate_unclosed=True), "before")


class TestParseJudgeOutput(unittest.TestCase):
    def test_clean_json_camel(self):
        raw = '{"taskScore": 90, "codeScore": 85, "testScore": 80, "hallucinationRate": 0.03, "confidence": 88, "overall": 86, "report": "好"}'
        r = parse_judge_output(raw)
        self.assertEqual(r.task_score, 90.0)
        self.assertEqual(r.hallucination_rate, 0.03)
        self.assertEqual(r.report, "好")

    def test_json_in_fence_with_think(self):
        raw = '<think>推理中</think>\n```json\n{"taskScore": 70, "codeScore": 60, "testScore": 50, "hallucinationRate": 0.1, "confidence": 80, "overall": 65, "report": "r"}\n```'
        r = parse_judge_output(raw)
        self.assertEqual(r.overall, 65.0)

    def test_snake_case_input(self):
        raw = '{"task_score": 70, "code_score": 60, "test_score": 50, "hallucination_rate": 0.1, "confidence": 80, "overall": 65, "report": "r"}'
        r = parse_judge_output(raw)
        self.assertEqual(r.task_score, 70.0)

    def test_missing_overall_filled(self):
        raw = '{"taskScore": 80, "codeScore": 80, "testScore": 80, "hallucinationRate": 0.0, "confidence": 80, "report": "r"}'
        r = parse_judge_output(raw)
        self.assertGreater(r.overall, 0.0)

    def test_garbage_returns_zero_with_error_report(self):
        r = parse_judge_output("完全不是 JSON 的文本")
        self.assertEqual(r.overall, 0.0)
        self.assertIn("解析失败", r.report)


class TestBuildPrompt(unittest.TestCase):
    def test_prompt_contains_keywords(self):
        p = build_prompt("实现 JSON 解析器", {"a.py": "print(1)"}, test_summary="5 passed")
        self.assertIn("taskScore", p)
        self.assertIn("实现 JSON 解析器", p)
        self.assertIn("a.py", p)
        self.assertIn("5 passed", p)


class TestAggregate(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(aggregate([])["count"], 0)

    def test_averages_and_pass_rate(self):
        results = [
            EvaluationResult(overall=90, task_score=90, code_score=90, test_score=90,
                             hallucination_rate=0.0, confidence=90),
            EvaluationResult(overall=50, task_score=50, code_score=50, test_score=50,
                             hallucination_rate=0.2, confidence=50),
        ]
        s = aggregate(results, pass_threshold=60)
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["avg_overall"], 70.0)
        self.assertEqual(s["avg_hallucination_rate"], 0.1)
        self.assertEqual(s["pass_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
