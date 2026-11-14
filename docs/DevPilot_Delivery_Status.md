# DevPilot 当前交付状态 / Current delivery status

更新：2026-11-14。本页只列当前能力、验证范围和缺口；逐轮原始记录见[交付历史](DevPilot_Delivery_History.md)。

## 现在能用什么

下表描述仓库代码；使用需要部署相应版本并完成账号、权限和 operator 配置。

| 能力                                                     | 代码状态                       | 使用边界                                                              |
| -------------------------------------------------------- | ------------------------------ | --------------------------------------------------------------------- |
| 项目/组件、QA 导入复核冻结、请求版本、冻结计划/v2 标准   | 已实现                         | 计划/hash 不授予执行权限；请求值与金标分离保护                        |
| 独立准入、有界 QA Worker、加密采集、人工复核、全样本汇总 | 已实现，执行默认关闭           | 未知交付不重发；采集成功/阈值达标不等于批准                           |
| 历史报告/Word 草稿、同基准复测                           | 已实现                         | 草稿与比较不自动批准、不自动再执行                                    |
| 双盲复核/独立仲裁、评估修订、独立历史报告/复测 Word/PDF  | 候选代码已实现，未部署         | `eval_0010..0012`；旧 owner 路径保持独立                              |
| 授权配置导出与外部技术元数据隔离接收                     | 候选代码已实现，未部署         | `eval_0013..0014`；不接纳敏感输出为可信证据                           |
| 独立本地 QA 命令、共享核心、锁定软件分发、加密输出       | 候选代码已实现                 | 默认离线；真实发送与输出模式分别同意                                  |
| 未完成/损坏本地输出的保留治理                            | 加密运行时和显式管理命令已实现 | 输出前 durable receipt；原 IDs/两个 hash/单独处置同意；无安全擦除保证 |
| 聊天、私有助手、请求调试、旧定时评测、模型管理           | 兼容入口保留                   | 模型调用需配置与授权；旧调度不代表新 QA 链调度完成                    |

入口与操作见[README](../README.md)、[文档导航](README.md)和[工作台范围](DevPilot_Evaluation_Workspace.md)。

## 代码、迁移与本机运行

| 项目               | 当前事实                                                                        |
| ------------------ | ------------------------------------------------------------------------------- |
| Git 源码           | `main`；精确工作区提交用 `git rev-parse HEAD` 查询，不用迁移号代替              |
| App 候选迁移头     | `eval_0014`；本轮保留治理修复没有新增迁移                                       |
| 最后留存的部署收据 | `0fd689da83a4ac7646250447fb6d044599a823c5` / `eval_0009`，属于历史验证          |
| 本机 Docker 观察   | 2026-11-14 四个 `devpilot-local` 业务容器均 stopped；旧镜像并不包含新候选模块   |
| 本轮操作           | 隔离测试与公开软件安装；没有部署、迁移业务 DB、生成生产 key 或调用真实模型/目标 |

只有重新启动并验真相应版本才能声称当前本机可用。历史健康和账号/数据保存记录见[本地升级记录](DevPilot_Local_Recovery_and_Upgrade.md)。

## 最近验证

- 管理命令模块的最终完整离线回归：**13,433 passed / 77 skipped / 11 deselected / 40 warnings**，881.28s；修改前基线为 13,393 passed。本地为默认 dev 安装，未安装 PostgreSQL extra 或启动独占 PostgreSQL；相关专项等按原门禁跳过。远端数据库服务门禁单独核验。
- 管理命令与原 retention API 联合 **80 passed**，含实际软件档案的命令/API/分发/输出/receipt 联合 **241 passed**；覆盖独立处置同意、原 ID/hash、活跃 lease、未知写删、中断及 stdout 丢失后原 ID 只读对账。Blocking IO **72 passed / 2 warnings**，领域 **15 / 58 passed**，完整后端 Ruff check/format **1,281 files** 通过。专项与全量重叠，不相加；运行时 durable receipt、硬退出等前轮回归及原始失败见交付历史。
- 新鲜六工具 hash-locked build → sdist/wheel → 12 依赖完整离线安装、新 no-system-site venv 中实际 plaintext/encrypted CLI、打开/清理/原 ID 对账与三条 retention 管理命令验证通过。两次软件档案逐字节一致，SHA256 `27aeb3cdb8df596b63fd2b0d8569e824ea5a13d11c4f36a315b7d1eb48af697f`；hash 不认证 dirty 来源。当前 allowlist 为 **37** 个第一方源码成员。

专项、联合和全量有重叠，不相加；skip 不是通过。前端/浏览器历史通过数没有在本轮本地重跑，Linux 验证不代替 Windows 验收。

运行时基线 **`deb1935d246fac1a8ed25d89ff16fd5ccd40c607`** 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43553100136)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43553100133)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43553100555)和 [Unit](https://github.com/helloboy829/DevPilot/actions/runs/43553100265)共 **4 workflows / 8 jobs 全成功**，含默认安装全量 collection、带 PostgreSQL 的完整后端、软件分发与实际安装导出。新管理命令模块的 SHA/CI 另行核验，不能沿用基线结果。更早的 collection 超时与有界诊断保留在历史，不宣称已确证根因或改变原门禁。

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
