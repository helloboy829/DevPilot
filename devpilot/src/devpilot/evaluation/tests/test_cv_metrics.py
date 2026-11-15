"""图像差异纯核心单测（零依赖，unittest）。"""

from __future__ import annotations

import json
import unittest

from devpilot.qa_cv_metrics import compute_image_diff


class TestImageDiff(unittest.TestCase):
    def test_identical_images(self):
        image = [[0, 10], [20, 255]]
        result = compute_image_diff(image, [row[:] for row in image])
        self.assertEqual(result["schema"], "qa-image-diff.v1")
        self.assertEqual(result["scope"], "technical_image_diff_only")
        self.assertEqual(result["dimensions"], {"width": 2, "height": 2, "pixels": 4})
        self.assertEqual(result["changed_pixels"], 0)
        self.assertEqual(result["changed_ratio"], 0.0)
        self.assertEqual(result["mean_absolute_error"], 0.0)
        self.assertEqual(result["max_absolute_error"], 0)
        self.assertTrue(result["identical"] and result["within_threshold"])
        self.assertEqual(result["approval"], "not_approved")
        json.dumps(result)

    def test_pixel_difference_and_threshold(self):
        result = compute_image_diff([[0, 0], [0, 0]], [[0, 0], [0, 10]], threshold=5)
        self.assertEqual(result["changed_pixels"], 1)
        self.assertEqual(result["changed_ratio"], 0.25)
        self.assertEqual(result["mean_absolute_error"], 2.5)
        self.assertEqual(result["max_absolute_error"], 10)
        self.assertFalse(result["identical"])
        self.assertFalse(result["within_threshold"])
        tolerated = compute_image_diff([[0, 0], [0, 0]], [[0, 0], [0, 10]], threshold=10)
        self.assertEqual(tolerated["changed_pixels"], 0)
        self.assertTrue(tolerated["within_threshold"])
        self.assertFalse(tolerated["identical"])

    def test_malformed_inputs_fail_closed(self):
        good = [[0]]
        cases = [
            (good, [[0], [0]], 0),
            (good, [[0, 0]], 0),
            ([[0, 0], [0]], good, 0),
            ([], good, 0),
            ([[0.5]], good, 0),
            ([[True]], good, 0),
            ([[256]], good, 0),
            ([[-1]], good, 0),
            (["x"], good, 0),
            ([[0]], good, -1),
            ([[0]], good, 256),
            ([[0]], good, True),
            ([[0]], good, 1.0),
            ([[0]] * 2_049, good, 0),
            ([[0] * 2_049], good, 0),
        ]
        for reference, candidate, threshold in cases:
            with self.subTest(reference=reference, threshold=threshold):
                with self.assertRaises(ValueError):
                    compute_image_diff(reference, candidate, threshold=threshold)


if __name__ == "__main__":
    unittest.main()
