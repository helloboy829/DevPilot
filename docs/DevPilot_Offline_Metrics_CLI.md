# 离线技术指标 CLI / Offline metrics CLI

日期：2026-11-15。候选源码，未部署、未接入 App 证据/API/UI。

## 范围

`devpilot.qa_metrics_cli` 把三个纯核心投影接到显式本地命令，只读取操作者指定的 JSON 文件：

```sh
PYTHONPATH=devpilot/src python -m devpilot.qa_metrics_cli stream \
  --observation observation.json
PYTHONPATH=devpilot/src python -m devpilot.qa_metrics_cli calibration \
  --pairs pairs.json
PYTHONPATH=devpilot/src python -m devpilot.qa_metrics_cli image-diff \
  --reference reference.json --candidate candidate.json --threshold 2
PYTHONPATH=devpilot/src python -m devpilot.qa_metrics_cli signoff \
  --requirement requirement.json
```

- `stream`：`qa-stream-metrics.v1`，TTFT/内容吞吐；缺失或不可观测保持 `null`/`unavailable`，不填零。
- `calibration`：`qa-judge-calibration.v1`，只统计双方确定的 pass/fail 配对；无确定配对时 `insufficient` 且数值为 `null`。
- `image-diff`：`qa-image-diff.v1`，等尺寸整数像素矩阵与包含式阈值；不读取图片文件、不解码。
- `signoff`：`qa-signoff-requirement.v1`，按显式 `required_distinct_approvers`/`distinct_approved_approvers`/`latest_decision` 返回 satisfied/固定 blockers；未定义策略时 `satisfied=null`，不存储或强制策略。
- 所有输出都带 `approval: "not_approved"`；结果不是质量 PASS、证据、正式批准或验收。

## 输入与失败关闭

- 每个输入必须是普通文件（拒绝符号链接/目录），大小 **1 字节–1 MiB**；打开后复核设备/inode，读取长度必须与 `lstat` 大小一致。
- 严格 UTF-8 JSON；解析拒绝重复键与 `NaN`/`Infinity`，并限制嵌套深度 ≤32、节点数 ≤20,000；核心层拒绝未知字段、类型伪装、越界、非等尺寸矩阵与非法阈值。
- 任何错误只向 stderr 输出固定 `Invalid metric input`，不反射路径、异常或输入内容；退出码 1（中断 130），不自动重试。
- 无网络客户端、无模型调用、无 App 数据库/证据读取、无输出文件写入或删除。

## 验证

```sh
PYTHONPATH=devpilot/src python -m unittest discover \
  -s devpilot/src/devpilot/evaluation/tests -p 'test_metrics_cli.py' -v
```

覆盖四条命令的成功输出、`null` 保持、阈值边界、缺失/非法/超限/符号链接输入、未知字段和错误信息不回显；CLI 专项 **13 passed**，`evaluation` 域合计 **62 passed**，`toolkit` **58 passed**。分发成员 allowlist 为 **49** 个第一方源码成员，分发测试 **72 passed**。

## 明确不包含

- 不接入 App 的证据、报告、批准或工作台；不读取真实 QA 输出/金标；不执行真实模型/目标。
- 不保存结果、不生成收据、不做来源认证；CLI 成功不是平台证据或正式批准。
- 无迁移、依赖、部署或权限变更。

English: an explicit offline CLI exposes the pure TTFT/throughput, judge-calibration, image-diff and sign-off-requirement projections over bounded local JSON files. It never uses the network or models, never fills missing metrics with zero, and is not evidence or approval.
