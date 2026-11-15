# 本地 QA 目录残留清单 / Local QA directory residue inventory

日期：2026-11-15。候选源码；不是证据、认证、批准或安全擦除。

## 范围

`python -m devpilot.local_qa_residue inventory` 对一个**显式指定**的本地 QA 结果目录，仅检查固定文件名是否存在及其大小/修改时间：

```sh
PYTHONPATH=devpilot/src python -m devpilot.local_qa_residue inventory \
  --directory /path/to/result \
  --confirm-metadata-only-directory-inventory
```

固定清单：`run-receipt.json`、`retention-receipt.json`、`retention.lock`、`observations.encrypted.jsonl`、`observations.jsonl`、`incomplete-output-disposal-request.json`、`incomplete-output-disposal-complete.json`。

输出 `local-qa-directory-residue.v1`：每项的 `present/size/mtime_ms`、`plaintext_copy_present`、`encrypted_output_present`、`content_status="not_inspected"`、`verdict="NOT_EVALUATED"`、`automatic_cleanup=false`、`approval="not_approved"`。

## 明确边界

- **不读取任何文件内容**、不认证、不解密、不计算 hash；不输出目录绝对路径或文件内容。
- **不发现其他文件**：只检查固定名称，不递归、不 glob；未知文件被忽略且不出现在输出。
- **不删除、不移动、不修复、不重试**；明文副本和崩溃产物仍需独立人工处置与授权。
- 目录必须是私有普通目录（POSIX 检查 owner 与 `0o077`），固定名称必须是普通文件；符号链接/其他类型失败关闭。
- 必须显式 `--confirm-metadata-only-directory-inventory`；错误只输出固定文案，不反射路径或异常。

## 验证

```sh
PYTHONPATH=devpilot/src python -m unittest discover \
  -s devpilot/src/devpilot/evaluation/tests -p 'test_local_qa_residue.py' -v
```

覆盖已知文件/缺失文件、纯元数据、未知文件忽略、显式确认、非目录与符号链接拒绝、CLI 成功与错误不回显。专项 **6 passed**；evaluation 域 **59 passed**、toolkit **58 passed**；分发 allowlist **49** 成员，分发测试 **72 passed**。

## 明确不包含

- 不接入 App、保留 API、批准或工作台；不证明输出完整性、来源、PASS 或安全擦除。
- 不管理明文副本的保留期、不建立自动清理器；无迁移、依赖或部署变更。

English: an explicit metadata-only inventory reports whether known local QA residue filenames exist, with size/mtime only. It never reads content, discovers other files, deletes anything or constitutes evidence/approval.
