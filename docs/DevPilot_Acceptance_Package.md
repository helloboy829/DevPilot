# DevPilot 候选验收包 / Candidate acceptance package

2026-11-15。本文件整理**源码候选**的验收路径、检查清单与回退边界。它不授权部署、数据外发、真实模型/目标调用或正式批准；实际替换环境、真实用户验收和 Windows 验收必须单独执行并记录收据。

## 1. 候选基线

| 项目           | 事实                                                                      |
| -------------- | ------------------------------------------------------------------------- |
| App 迁移头     | `eval_0015`（正式批准两表）                                               |
| 精确源码       | 以实际 `git rev-parse HEAD` 为准；本文件不固定 SHA                          |
| CI 收据        | 每个新 SHA 单独核验 Lint / Blocking IO / Frontend / Replay E2E / Unit      |
| 本地门禁       | 见[当前状态](DevPilot_Delivery_Status.md)的“最近验证”；不与 CI 相加       |
| 部署状态       | 历史部署收据停在 `eval_0009`；本机业务容器已于 2026-11-15 观察为不存在     |

验收只针对**同一 SHA** 的源码与其 CI 结果；不能用前一 SHA 的 Actions、旧镜像或历史健康记录代替。

## 2. 验收前置（operator 责任）

- [ ] 私有 `config.yaml`、`extensions_config.json` 与凭据由 operator 提供；仓库内不提交。
- [ ] `DEVPILOT_REQUEST_ENCRYPTION_KEY`（请求版本与证据加密）已按 secret 管理配置；缺失时只验证失败关闭。
- [ ] 模型目录与 `DEVPILOT_MODEL_ENCRYPTION_KEY`（如启用）独立配置；不把模型 key 当作 QA 目标授权。
- [ ] 执行策略保持默认关闭；启用需独立 operator 决定、目标 allowlist、权限与显式同意。
- [ ] 升级前在**在线一致性备份**下完成；确认备份可恢复（SQLite 需含 WAL，恢复会导致备份后写入丢失）。
- [ ] 账号与角色（admin / 普通 owner / 独立审阅人 / 仲裁人 / 具名审批人）按职责分离准备，至少需要 5 个不同账号才能走完独立复核＋正式批准。
- [ ] 固定 Compose project、端口、卷与挂载；不启动第二个同端口栈。

## 3. 合成工作台验收清单

使用合成项目与合成 QA 数据，不接入客户素材、真实目标或生产库。

### 3.1 登录与权限

- [ ] 真实密码/JWT/CSRF 登录；匿名访问被拒。
- [ ] 未授权账号看不到他人项目；服务端 owner 隔离生效（跨 owner 返回 404）。
- [ ] 内部 token/非人类调用者被审阅、证据与运维路由拒绝。
- [ ] `evaluation_projects:{read,write,review}` 与 `evaluation_operations:read` 按需授予；read 不隐含 review/write。

### 3.2 数据与计划

- [ ] 创建项目/组件，导入合成 QA，复核后冻结；请求值/金标不出现在列表或聊天。
- [ ] 保存请求版本只返回结构元数据；缺失 key 时失败关闭。
- [ ] 冻结计划固定请求/数据版本、JSON 映射与预算；修改任一来源后旧 hash 不再匹配。

### 3.3 执行（默认关闭）

- [ ] 未配置 operator 策略时执行不可启用；任何 UI/API 都不能自行开启。
- [ ] 若 operator 明确启用：仅合成目标、显式同意、单次有界采集；未知写入不重发，只按原 ID 对账。
- [ ] 取消/关闭在重复取消后排空；deadline 不被当作 Worker 死亡或释放依据。

### 3.4 独立复核、评估与批准

- [ ] 两名不同盲审人 + 第三名仲裁人；owner 不能兼任；仅授予冻结 case。
- [ ] 缺失/不确定证据不能 PASS；历史轮次结果不被当前复核覆盖。
- [ ] 全样本评估固定 ALL 分母；`review_complete` 且无 blockers 才能归档评估修订。
- [ ] 正式批准要求：具名审批人 ≠ owner 且 ≠ 该 run 任一盲审/仲裁；评估哈希匹配；冻结阈值（若定义）`met`；显式确认。
- [ ] 撤销追加新 revision 并要求理由；审计按 run 递增；重复载荷幂等，不同载荷同 ID 冲突。
- [ ] case PASS、复核完整与阈值达标都不会自动生成批准。

### 3.5 报告、复测与导出

- [ ] 历史报告/复测从显式选择的历史 revision 生成，不读最新来源。
- [ ] Markdown/Word/PDF 草稿为未批准草稿；不自动发布或外发。
- [ ] 授权导出需独立 grant、三次创建同意与单独下载同意；未知 PUT/GET404 只按原 ID 对账。
- [ ] 外部技术声明隔离接收不把声明当作平台证据或批准；不导入敏感输出。

### 3.6 失败与未知

- [ ] 未知写入不重试、不生成替代 ID；刷新只读原 ID。
- [ ] 数据库/加密/权限失败返回通用错误，不回显 SQL、参数、金标或密文。
- [ ] 缺失证据、skip 或超时不得记为通过；skip 需记录原因。

## 4. 回退边界

- 保留升级前镜像引用与可恢复备份；数据库升级后**不能只换回旧镜像**宣称完整回退。
- 恢复旧备份会丢弃备份之后的写入；需要停写与在途请求治理。
- 不在业务库上试 downgrade；候选用合成副本演练（见[恢复矩阵](DevPilot_Candidate_Upgrade_Recovery.md)）。
- 页面/接口冒烟、浏览器零重试与账号只读检查属于验收证据；不自动触发真实执行或模型调用。

## 5. 明确不包含

- 不包含部署、生产配置、生产 key、真实目标/模型调用、客户数据、正式批准或安全擦除证明。
- 不包含 Windows 本地验收、PostgreSQL 原生恢复、长期稳定性或性能承诺。
- Linux/容器结果不替代 Windows 与真实用户验收。

## 6. 签收记录（由验收人填写）

| 项目             | 结果 | 证据（SHA / Actions / 截图或日志路径） |
| ---------------- | ---- | -------------------------------------- |
| 精确 SHA CI      |      |                                        |
| 登录与 RBAC      |      |                                        |
| 计划冻结与哈希   |      |                                        |
| 独立复核/仲裁    |      |                                        |
| 评估与 ALL 分母  |      |                                        |
| 正式批准/撤销    |      |                                        |
| 报告/复测/导出   |      |                                        |
| 未知写对账       |      |                                        |
| 备份与回退演练   |      |                                        |
| Windows 验收     |      |                                        |

English: this package lists the synthetic acceptance path, checklist, rollback limits and non-claims for a source candidate. It does not authorize deployment, external data transfer, real model/target calls, production keys or formal approval; Linux/container evidence does not replace Windows or real-user acceptance.
