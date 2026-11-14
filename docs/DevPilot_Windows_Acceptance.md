# Windows 验收 Runbook / Windows acceptance runbook

2026-11-15。本文件描述在 Windows 11 + Docker Desktop（WSL2 后端）上验证同一 SHA 候选的步骤与证据边界。它不授权部署、真实模型/目标调用或生产数据；Linux/容器结果不替代本验收。

## 1. 前置

- [ ] Windows 11、Docker Desktop（WSL2 引擎）、Git for Windows（含 Git Bash）、make（Git Bash/WSL）或直接用 `docker compose`。
- [ ] 端口 `2026` 仅绑定回环；确认 `http://127.0.0.1:2026` 未被其他服务占用。
- [ ] 私有 `config.yaml`、`extensions_config.json`、`.env` 由 operator 提供；仓库不提交。
- [ ] 按需配置 `DEVPILOT_REQUEST_ENCRYPTION_KEY`、`DEVPILOT_MODEL_ENCRYPTION_KEY`、`BETTER_AUTH_SECRET`、内部 token；不要把 key 写入仓库或聊天。
- [ ] 升级前完成在线一致性备份（SQLite 需含 WAL；恢复会丢失备份后的写入）。
- [ ] 磁盘剩余 ≥ 10 GB；Docker 镜像/卷归属于本项目，避免误删其他项目资源。

## 2. 启动与健康

```sh
docker compose version
python scripts/docker_health.py --project ACTUAL_COMPOSE_PROJECT --timeout 5
```

- 首次或重建：`docker compose -p ACTUAL_COMPOSE_PROJECT -f docker/docker-compose.yaml up -d`（或按 README 的 `make docker-start`）。
- 健康脚本只读元数据；`status=ok` 仅表示服务进程/健康检查通过，不证明登录、数据库迁移或业务可用。
- 打开 `http://127.0.0.1:2026`；确认匿名访问被拒绝，登录页正常加载。

## 3. 合成验收清单

按[候选验收包](DevPilot_Acceptance_Package.md)执行，至少覆盖：

- [ ] 真实密码/JWT/CSRF 登录；RBAC 与 owner 隔离；内部 token 被拒。
- [ ] 项目/QA 导入复核冻结、请求版本、冻结计划与哈希。
- [ ] 执行保持默认关闭；未配置 operator 策略时 UI/API 不能启用。
- [ ] 两名盲审 + 仲裁；全样本评估；正式批准/撤销与审计列表；只读预检；项目级索引。
- [ ] 报告/复测/Word/PDF 仅显式历史来源；未知写入按原 ID 对账。
- [ ] 失败路径：缺失 key、无效哈希、未知 ID、权限不足均失败关闭且不回显敏感值。

## 4. Windows 专项检查

- [ ] **WAL/文件锁**：在 Windows 挂载卷上执行备份/恢复演练时，确认 `-wal`/`-shm` 与主库一致；只复制主文件的反例必须能观察到丢失。
- [ ] **路径分隔符**：报告/证据/导出路径在 Windows 下不出现混合分隔符导致的 404/500；JSON 报告使用 POSIX 相对路径。
- [ ] **事件循环**：后端在 Windows 保留 Selector 策略（默认）；不因测试通过而改用其它策略。
- [ ] **venv**：`backend/.venv` 是 Linux 环境，**不能**在 Windows 宿主直接执行；Windows 原生测试需另建 Python 3.12 环境，容器测试用 Linux venv。
- [ ] **ACL**：`catalog.key`、SQLite 文件与输出目录的 Windows ACL 由 operator 收紧；本仓库不声明自动 ACL。
- [ ] **浏览器**：Edge/Chrome 桌面与窄屏各走一遍；零自动重试；不做真实目标/模型调用。

## 5. 证据

- 精确 `git rev-parse HEAD` 与该 SHA 的 Lint/Blocking IO/Frontend/Replay/Unit Actions 链接。
- `docker_health.py` 输出（脱敏）、登录与各清单页面的截图或文字记录。
- 失败/跳过项的原因；skip 不算通过。
- 资源收尾：记录本轮容器/端口/卷；只停止本轮资源，不全局 prune、不删除业务卷或他人项目资源。

## 6. 回退

- 保留升级前镜像引用与可恢复备份；不只在业务库上试 downgrade。
- 恢复旧备份会丢弃之后的写入；先停写并处理在途请求。
- 页面/接口冒烟通过不等于正式批准；正式质量验收仍需独立批准记录。

## 7. 明确不包含

- 自动化部署、生产配置、真实模型/目标、客户数据或正式批准。
- 安全擦除、长期稳定性、性能承诺或 PostgreSQL 原生恢复。
- 以本文件替代 Linux CI 或真实用户验收。

English: this runbook lists Windows 11 + Docker Desktop steps for the same SHA: prerequisites, health, the synthetic checklist, Windows-specific WAL/lock/path/event-loop/venv/ACL checks, evidence, rollback and explicit non-claims. It does not authorize deployment, real calls, production data or approval.
