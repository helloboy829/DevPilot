# DevPilot 部署与运维设计 v3.0

> 2026-11-06；当前拓扑 + 目标运维要求，不代表已完成生产验证。

## 1. 当前服务与启动

| 服务 | 端口 | 角色 |
| --- | --- | --- |
| Nginx | 2026 | 统一公开入口 |
| Gateway | 8001 | REST + 嵌入式 LangGraph runtime |
| Frontend | 3000 | Next.js |
| Provisioner | 8002 | 仅 provisioner/K8s 沙箱模式需要 |

Compose 入口默认发布到 127.0.0.1；Gateway 的容器内 0.0.0.0 不是对外发布。公网/局域网发布需显式 BIND_HOST、TLS/认证和网关策略，不能为方便改裸端口绑定。
/api/langgraph/* 经 Nginx 改写到 Gateway /api/*；其他 /api/* 走业务 routers。SSE 不缓冲/压缩，静态文本仍可压缩。

依赖 Python 3.12+、uv、Node.js 22+、项目锁定 pnpm；Windows 按 Install.md 选择受支持运行方式，不假定 make/bash 原生可用。host pnpm 使用 scripts/pnpm.py。
根目录 config.example.yaml → config.yaml、extensions_config.example.json → extensions_config.json；真实密钥与配置不可提交 Git。make doctor / make dev / make up 作用见根 AGENTS.md。

## 2. 当前部署阻断

**已修复（2026-11-12）**：backend 依赖 ../devpilot，早期 Dockerfile 未拷贝该包，`uv sync` 以 `Distribution not found at: file:///app/devpilot` 失败。现 builder 在同步依赖前拷贝 `devpilot`，runtime 从 builder 复制 `/app/devpilot`，开发 Compose 挂载 `../devpilot` 到同一路径；回归见 `backend/tests/test_backend_image_devpilot.py`。本地已完成干净构建、四容器 healthy 与 `eval_0014` 迁移核验，异机/Linux CI 构建仍需单独确认。

## 3. 目标部署形态

- 单人试点：Gateway + Worker 可同部署，但任务仍持久化；SQLite + 受控文件卷。
- 团队受控使用：PostgreSQL + 独立有界 Worker + artifact 卷/对象存储；压测 Worker 与交互隔离。
- Redis/专用向量库按实测引入；Provisioner 仅实际需要隔离脚本执行时启用。

目标 evaluation profile 关闭非核心外连/IM/定时能力、隐藏非评测 UI；这不是当前已有的统一配置项，需实现 capability 与集成测试。保留助手所需 LangGraph/鉴权/存储。

## 4. 安全运营

私网组件通过管理员维护域名/端口/网段允许列表；拒绝 metadata/link-local/回环等未批准目标，DNS 校验绑定连接地址，重试/重定向再次应用策略。网络侧 egress 防线配合应用层，不用 URL 字符串黑名单替代。
TLS 默认验证，企业自签证书通过受信 CA 配置；遗留 HTTP-only 组件需显式风险豁免与网络隔离，不能全局 verify=False。
密钥服务或加密存储的主密钥不与密文放同库，日志脱敏并轮换。上传限额、恶意文件/解压炸弹隔离、artifact 路径校验与下载权限。LocalSandbox 不是强隔离边界，不为评测默认开启 host bash。

## 5. 配额、故障与应急

每租户/用户/项目/目标/全局限制并发、请求、运行数、时长、数据大小及费用；排队有界。压测批准窗口、紧急停止、目标健康异常降载和取消传播。
Job lease/heartbeat 过期告警；效果按规则恢复、性能标 interrupted 并新运行，不悄悄续接。目标端无法停止的请求记录未确定副作用，不声称全部已撤销。
监控队列时长、卡住任务、错误率、发生器 CPU/内存/网络、磁盘/存储、裁判不可用和预算。日志以 project/run/job/trace 关联，不落敏感完整响应。

## 6. 备份、迁移与发布

备份 DB、artifact manifest/数据、模板、授权元数据、配置版本及密钥服务恢复流程；SQLite 用一致性备份方案，不直接复制活跃 WAL 数据文件。恢复演练验证 FK、hash 和权限；组织确定 RPO/RTO 后测试，不凭文档承诺。
发布先离线回归→镜像 import/迁移烟测→历史项目试点→小范围；数据库 additive migration，保留旧读兼容。回滚应用不删新证据；知识索引、Prompt 和模板可回滚版本。
真实外部评测与负载测试单独 opt-in。故障支持包必须脱敏，禁止上传目标凭据、隐私数据和完整验收答案。

## 7. 调试、导出与复核运维边界

调试台显示实际 Worker 执行域并复用出站策略；复核附件走鉴权/隔离渲染，不由浏览器自动访问任意外链。独立导出工程使用受控依赖源与锁定版本，可选受审 wheelhouse；产物校验、下载权限/过期和敏感导出审计独立配置，禁止把 secrets 或工作机路径夹带进 ZIP。
外部结果压缩包按不可信上传处理，限制解压大小/文件数并拒绝路径穿越/链接逃逸；验证后仍标 provenance/trust，不能跳过人工采信。已下载工程不能由平台保证停止或继续强制网络政策，应通过目标侧凭据/配额/网络控制撤销访问。
监控补充 review 队列/领取过期/冲突与裁决重算失败、export 自检/依赖失败、confirmation 过期；已发布报告修订的通知失败可重试但不覆写旧件。
