"""transports.py 纯逻辑单测（无网络）。

运行（repo 根目录）：
    python -m unittest discover -s devpilot/toolkit/tests -v
"""

from __future__ import annotations

import unittest

from devpilot.toolkit.transports import (
    _iter_sse_data,
    dify_business_failed,
    estimate_tokens,
)


class _FakeLinesResponse:
    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class TestEstimateTokens(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_cjk_counts_one_each(self):
        # 4 个 CJK 字符 -> ~4 token
        self.assertGreaterEqual(estimate_tokens("你好世界"), 4)

    def test_ascii_four_chars_per_token(self):
        # 8 个 ascii 字符 -> ~2 token，但至少 1
        self.assertEqual(estimate_tokens("abcdefgh"), 2)

    def test_short_ascii_min_one(self):
        self.assertEqual(estimate_tokens("hi"), 1)


class TestDifyBusinessFailed(unittest.TestCase):
    def test_succeeded_is_not_failed(self):
        self.assertFalse(dify_business_failed({"status": "succeeded", "error": None}))

    def test_failed_status(self):
        self.assertTrue(dify_business_failed({"status": "failed"}))

    def test_stopped_status(self):
        self.assertTrue(dify_business_failed({"status": "stopped"}))

    def test_error_dict(self):
        self.assertTrue(dify_business_failed({"status": "succeeded", "error": {"code": "x"}}))

    def test_error_empty_string_is_not_failed(self):
        self.assertFalse(dify_business_failed({"status": "succeeded", "error": ""}))


class TestIterSseData(unittest.IsolatedAsyncioTestCase):
    async def test_extracts_data_lines(self):
        resp = _FakeLinesResponse(
            [
                ": keepalive",
                "",
                "data: {\"a\": 1}",
                "data: [DONE]",
                "event: message",
            ]
        )
        out = [line async for line in _iter_sse_data(resp)]
        self.assertEqual(out, ['{"a": 1}', "[DONE]"])


if __name__ == "__main__":
    unittest.main()
