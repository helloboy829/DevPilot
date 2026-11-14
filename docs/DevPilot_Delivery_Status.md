# DevPilot 当前交付状态 / Current delivery status

更新：2026-11-14。本页只列当前能力、验证范围和缺口；逐轮原始记录见[交付历史](DevPilot_Delivery_History.md)。

## 现在能用什么

下表描述仓库代码；使用需要部署相应版本并完成账号、权限和 operator 配置。

| 能力                                                     | 代码状态                       | 使用边界                                                                     |
| -------------------------------------------------------- | ------------------------------ | ---------------------------------------------------------------------------- |
| 项目/组件、QA 导入复核冻结、请求版本、冻结计划/v2 标准   | 已实现                         | 计划/hash 不授予执行权限；请求值与金标分离保护                               |
| 独立准入、有界 QA Worker、加密采集、人工复核、全样本汇总 | 已实现，执行默认关闭           | 未知交付不重发；采集成功/阈值达标不等于批准                                  |
| 历史报告/Word 草稿、同基准复测                           | 已实现                         | 草稿与比较不自动批准、不自动再执行                                           |
| 双盲复核/独立仲裁、评估修订、独立历史报告/复测 Word/PDF  | 候选代码已实现，未部署         | `eval_0010..0012`；旧 owner 路径保持独立                                     |
| 授权配置导出与外部技术元数据隔离接收                     | 候选代码已实现，未部署         | `eval_0013..0014`；不接纳敏感输出为可信证据                                  |
| 独立本地 QA 命令、共享核心、锁定软件分发、加密输出       | 候选代码已实现                 | 默认离线；真实发送与输出模式分别同意                                         |
| 未完成/损坏本地输出的保留治理                            | 加密运行时和显式管理命令已实现 | 输出前 durable receipt；原 IDs/两个 hash/单独处置同意；无安全擦除保证        |
| 候选 SQLite 升级与旧备份恢复演练                         | 合成回归已实现                 | 真实双 ledger、39 张历史表、WAL 在线备份与新路径还原；不是业务部署或无损回退 |
| 聊天、私有助手、请求调试、旧定时评测、模型管理           | 兼容入口保留                   | 模型调用需配置与授权；旧调度不代表新 QA 链调度完成                           |

入口与操作见[README](../README.md)、[文档导航](README.md)和[工作台范围](DevPilot_Evaluation_Workspace.md)。

## 代码、迁移与本机运行

| 项目               | 当前事实                                                                                  |
| ------------------ | ----------------------------------------------------------------------------------------- |
| Git 源码           | `main`；精确工作区提交用 `git rev-parse HEAD` 查询，不用迁移号代替                        |
| App 候选迁移头     | `eval_0014`；本轮合成恢复验证没有新增迁移                                                 |
| 最后留存的部署收据 | `0fd689da83a4ac7646250447fb6d044599a823c5` / `eval_0009`，属于历史验证                    |
| 本机 Docker 观察   | 2026-11-14 四个 `devpilot-local` 业务容器均 stopped；旧镜像并不包含新候选模块             |
| 本轮操作           | 隔离合成升级/备份/恢复验证；没有部署、复制或迁移业务 DB、生成生产 key 或调用真实模型/目标 |

只有重新启动并验真相应版本才能声称当前本机可用。历史健康和账号/数据保存记录见[本地升级记录](DevPilot_Local_Recovery_and_Upgrade.md)。

## 最近验证

- 候选恢复回归的最终完整离线套件：**13,441 passed / 77 skipped / 11 deselected / 40 warnings**，934.37s；修改前基线为 13,433 passed（906.24s）。本地默认 dev 安装未配置 PostgreSQL extra/独占服务器，相关专项等按原门禁跳过。远端数据库服务门禁单独核验。
- [最终 SQLite 恢复矩阵](DevPilot_Candidate_Upgrade_Recovery.md)专项 **8 passed**（59.15s），验证 39 → 44 → 45 → 47 → 49 → 51 张表及 ALL 历史行/schema、WAL/账号/报告/复测/Word。与五组已有迁移联合 **13 passed / 5 skipped**；Blocking IO **72 passed / 2 warnings**，领域 **15 / 58 passed**，最终完整后端 Ruff check/format **1,282 files** 通过。专项和全量重叠，不相加；skip 不是通过。
- 前一 `7ba1484` 的管理命令/原 retention API 联合 **80 passed**，带实际软件的联合 **241 passed**，六工具构建→12依赖完整离线安装与三条实际管理命令已验证；本轮未改软件源码/依赖或重建分发。档案 SHA256 `27aeb3cdb8df596b63fd2b0d8569e824ea5a13d11c4f36a315b7d1eb48af697f` 只属于前轮构建，当前 allowlist 为 **37** 个第一方源码成员。原始失败与逐轮门禁见交付历史。

专项、联合和全量有重叠，不相加；skip 不是通过。前端/浏览器历史通过数没有在本轮本地重跑，Linux 验证不代替 Windows 验收。

基线 **`7ba1484b098d7a29a0a737400ff321d0ccbc8001`** 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43558000440)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43558000459)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43558000384)和 [Unit](https://github.com/helloboy829/DevPilot/actions/runs/43558000487)共 **4 workflows / 8 jobs 全成功**，含默认安装全量 collection、带 PostgreSQL 的完整后端、软件分发与实际安装导出。本轮合成恢复回归的 SHA/CI 另行核验，不能沿用基线结果。更早的 collection 超时与有界诊断保留在历史，不宣称已确证根因或改变原门禁。

原始红灯、修复原因和逐轮收据见[交付历史](DevPilot_Delivery_History.md)。push、本地通过、CI 成功和部署是独立事实。

## 下一步优先级

| 优先级 | 工作                                                   | 退出条件                                                                         |
| ------ | ------------------------------------------------------ | -------------------------------------------------------------------------------- |
| P0     | 当前源码 CI、环境与候选升级验收闭环                    | 精确 SHA 门禁、当前镜像源码核对、数据/配置保护、隔离迁移及回退演练；部署另行执行 |
| P1     | 本地明文副本与更广泛崩溃产物治理、Windows 验收         | 分别绑定原身份/用途/保留同意，旧目录不补造回执；新平台实际安装/锁/处置验证       |
| P1     | 独立版本化正式批准                                     | 固定历史来源、职责分离、审批修订/撤销及用户验收；不能把 case PASS 当批准         |
| P1     | Lost Worker 安全处置与新 QA 调度准入                   | 证明旧 Worker 不能发送后再讨论释放；未知请求绝不重发；不能沿用旧调度绕准入       |
| P2     | 敏感外部证据治理、CV/流式指标/模型裁判、整改与知识闭环 | 各自授权、隔离、证据/计量与人工审查；缺失指标不填零、不判 PASS                   |

开发环境恢复不必等所有 P1/P2 功能完成；正式质量验收依赖独立批准及相应业务能力。具体交付以模块退出条件为准，项目整体尚未完成。

English: Source capabilities, candidate migrations, exact-commit verification and observed runtime are tracked separately. Business containers were stopped at the recorded observation; no deployment or real calls were performed. Encrypted runtime retention receipts and explicit management commands are implemented; plaintext-copy/crash-artifact governance, Windows acceptance, independent approval and safe lost-worker/scheduling operations remain open.
