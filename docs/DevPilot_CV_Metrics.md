# CV 图像差异纯核心 / Image diff core

2026-11-15。新增 `devpilot.qa_cv_metrics.compute_image_diff`：对调用方已安全解码的两份**等尺寸整数像素矩阵**做技术差异统计。它不代表视觉质量、PASS 或批准，也不解码图片、不访问网络、不调用模型。

## 输入

- `reference` / `candidate`：非空矩形 `list[list[int]]`，每边 1–2048，元素为严格整数 0–255（布尔/浮点/越界拒绝）；尺寸必须一致。
- `threshold`：严格整数 0–255（包含该绝对差视为未变化）。
- 任何畸形、越界、非矩形或不同尺寸输入立即 `ValueError`（失败关闭），不填零、不插值。

## 输出（`qa-image-diff.v1`）

- `scope=technical_image_diff_only`，`approval=not_approved`。
- `dimensions`：`width`、`height`、`pixels`。
- `threshold`、`changed_pixels`（绝对差 > threshold 的像素数）、`changed_ratio=round(changed/pixels,6)`。
- `mean_absolute_error=round(sum|diff|/pixels,4)`、`max_absolute_error`。
- `identical`：所有像素相等；`within_threshold`：无像素超过容差。两者都是技术事实，不是质量结论。

## 明确不包含

- 不负责图片解码/格式校验、缩放/对齐/裁剪、掩膜、色彩空间或多帧处理；调用方必须先以安全方式解码为整数矩阵。
- 未接入 App 证据、API、报告或 UI；不持久化、不参与阈值、批准或导出。
- 不含 SSIM/LPIPS/感知指标或模型裁判；缺失/不可比较不是零差异。

## 验证

```sh
PYTHONPATH=devpilot/src python -m unittest discover -s devpilot/src/devpilot/evaluation/tests -p 'test_cv_metrics.py' -v
```

覆盖：完全相同、单像素差异与阈值、MAE/max/ratio、尺寸不一致/非矩形/空/类型伪装/越界/阈值伪装与越界/超尺寸失败关闭。分发 allowlist 同步包含新源码与测试（43 个第一方成员）。

English: a pure technical diff over equal integer pixel matrices, with strict bounds and an inclusive threshold. It is not image decoding, perceptual quality, approval, or a model call; malformed or incomparable inputs fail closed.
