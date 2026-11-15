"""技术性图像差异统计：纯整数像素矩阵、零网络、零解码、零模型调用。

只比较调用方已安全解码的等尺寸整数像素矩阵；结果不代表视觉质量、PASS
或批准。畸形/越界/非等尺寸输入立即失败关闭，不填零、不插值。
"""

from __future__ import annotations

_MAX_SIDE = 2_048


def _matrix(value):
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_SIDE:
        raise ValueError("Invalid image matrix")
    width = None
    for row in value:
        if not isinstance(row, list) or not 1 <= len(row) <= _MAX_SIDE:
            raise ValueError("Invalid image matrix")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ValueError("Invalid image matrix")
        for pixel in row:
            if type(pixel) is not int or not 0 <= pixel <= 255:
                raise ValueError("Invalid image pixel")
    return width


def compute_image_diff(reference, candidate, *, threshold=0):
    """Return a fixed technical diff projection for two equal integer matrices.

    ``threshold`` is the inclusive per-pixel absolute-difference tolerance.
    ``identical`` means every pixel is equal; ``within_threshold`` means no
    pixel exceeds the tolerance. Both are technical facts, not quality verdicts.
    """
    if type(threshold) is not int or not 0 <= threshold <= 255:
        raise ValueError("Invalid threshold")
    width = _matrix(reference)
    if _matrix(candidate) != width or len(candidate) != len(reference):
        raise ValueError("Image dimensions differ")
    height = len(reference)
    pixels = width * height
    total, maximum, changed = 0, 0, 0
    for reference_row, candidate_row in zip(reference, candidate):
        for left, right in zip(reference_row, candidate_row):
            difference = abs(left - right)
            total += difference
            maximum = max(maximum, difference)
            if difference > threshold:
                changed += 1
    return {
        "schema": "qa-image-diff.v1",
        "scope": "technical_image_diff_only",
        "dimensions": {"width": width, "height": height, "pixels": pixels},
        "threshold": threshold,
        "changed_pixels": changed,
        "changed_ratio": round(changed / pixels, 6),
        "mean_absolute_error": round(total / pixels, 4),
        "max_absolute_error": maximum,
        "identical": maximum == 0,
        "within_threshold": changed == 0,
        "approval": "not_approved",
    }


__all__ = ["compute_image_diff"]
