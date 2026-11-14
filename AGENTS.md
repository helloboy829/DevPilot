# DevPilot Agent 开发指南

## 先读什么

- [当前状态](docs/DevPilot_Delivery_Status.md)：区分源码、候选迁移、验证和本机运行。
- [设计与合同索引](docs/README.md)：按任务阅读对应合同；目标设计不等于已交付能力。
- [后端指南](backend/AGENTS.md) / [前端指南](frontend/AGENTS.md)：模块实现、命令与测试要求。
- [持续约束与历史切片](docs/DevPilot_Agent_Contracts.md)：保留原指南全部细节；相关模块的合同约束仍适用，日期和通过数仅属于原轮次。

## Monorepo 与依赖方向

| 位置                               | 职责                                           |
| ---------------------------------- | ---------------------------------------------- |
| `backend/app/`                     | FastAPI Gateway、账号/权限、评测业务与 IM 接入 |
| `backend/packages/harness/`        | DeerFlow Agent、工具、中间件、运行与持久化框架 |
| `backend/packages/extension-api/`  | 不依赖宿主业务的公开扩展协议                   |
| `devpilot/src/devpilot/`           | 评测工具包、共享 QA 核心和独立本地命令         |
| `frontend/`                        | Next.js 工作台与兼容聊天界面                   |
| `docker/` / `scripts/`             | Compose、nginx、构建、诊断与本地编排           |
| `contracts/` / `skills/` / `docs/` | 跨组件协议、公开技能与项目文档                 |

依赖保持 App → Harness、App → devpilot；Harness 不导入 `app.*`。共享 QA runner 只有一套版本化核心；debug、平台与本地适配器保留各自授权、配额和耐久边界，不另造模型生成的 runner。

默认入口是 `http://127.0.0.1:2026`。nginx 转发前端 3000 和 Gateway 8001；`/api/langgraph/*` 改写到 Gateway 的嵌入式 Agent runtime。Provisioner 8002 仅在指定沙箱模式下使用。Compose 发布端口默认绑定回环地址，新端口必须显式声明 bind host。

## 根命令与模块命令

以下命令只说明用途，不自动授权部署或调用模型。

```sh
# 仓库根目录：完整应用与诊断
make check
make config
make doctor
make dev                 # 宿主开发环境
make docker-start        # Docker 开发环境
python scripts/docker_health.py --project ACTUAL_COMPOSE_PROJECT

# 后端：Python 3.12；完整离线测试包含领域测试
cd backend
uv sync --frozen --group dev
make lint
make test-blocking-io
make test
```

前端宿主命令统一从仓库根目录经 `python scripts/pnpm.py check`、`python scripts/pnpm.py test` 等调用，保留直接 pnpm / pnpm.cmd / Corepack 的顺序及项目锁定版本。详见 [安装](Install.md)、[贡献](CONTRIBUTING.md)和[前端指南](frontend/AGENTS.md)。

## 跨模块约定

- 新功能/缺陷先写失败回归，再最小修复；后端完整离线套件、相关领域/Blocking IO 与格式门禁按模块执行。前端按模块运行类型、lint、单测和相关浏览器/API 回归；不抬预算、延长超时或减弱断言隐藏失败。
- 小模块验证后提交并推送，记录精确 SHA 与实际 Actions；push 不是 CI 成功，不把上一 SHA 的结果移用到新提交。修复可归因失败后再推进后续模块。
- 用户可见变化同步 README，架构/开发约定同步相应指南，交付事实进入状态页；历史记录单独保留。文档使用中文/英文，不清理运行时语言或许可证。
- 私有配置、key、账号、数据库、客户资料、输出及本地证据不得提交或复制到隔离环境。根目录 `config.yaml`、`extensions_config.json` 是私有运行配置；不覆盖已有值，不从环境或旧机器推断授权。
- 冻结 ALL 输入分母、版本/hash、预算与历史记录；观察、采集成功、人工判断、阈值达标和正式批准分别建模。缺失/不确定证据不能 PASS。
- 未知写入/交付只用原 ID 只读对账，不自动重试、修复、重发或续跑；deadline 不证明 Worker 死亡。独立复核保留双盲、独立仲裁、窄授权和过期 fence。
- 执行、数据外发、敏感打开和明文/加密输出保持分别授权；默认不启用执行、不生成生产 key、不调用真实模型/目标、不部署。Linux 验证不替代 Windows 或真实用户验收。
- 生产前端在 builder 构建，服务启动只运行已构建产物；保持已有挂载、配置和账号。业务运行状态必须重新观察，历史部署收据不证明当前服务健康。

## Docker 生命周期

记录本轮启动的 CI 容器，在测试/证据导出完成后仅停止本轮资源。先核目的、状态、数据、归属及替代验证，再按确切 ID 退役过期 DevPilot 验证容器；镜像删除前检查**全部容器**引用。保留业务、卷、必要回退及有用缓存，不使用 force、全局 prune、卷删除、后台清理或 Desktop 重启。镜像清理不证明宿主 RAM 释放或 VHDX 压缩。详见 [Docker 运维](docs/DevPilot_Docker_Diagnostics.md)。

English: This guide owns repository boundaries and shared rules. Module guides own implementation detail; dated contract notes retain their constraints but do not establish current verification, deployment or approval.
