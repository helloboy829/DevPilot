# DevPilot 当前交付状态 / Current delivery status

更新：2026-11-14。本页只列当前能力、验证范围和缺口；逐轮原始记录见[交付历史](DevPilot_Delivery_History.md)。

## 现在能用什么

下表描述仓库代码；使用需要部署相应版本并完成账号、权限和 operator 配置。

| 能力                                                     | 代码状态                         | 使用边界                                                            |
| -------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------- |
| 项目/组件、QA 导入复核冻结、请求版本、冻结计划/v2 标准   | 已实现                           | 计划/hash 不授予执行权限；请求值与金标分离保护                      |
| 独立准入、有界 QA Worker、加密采集、人工复核、全样本汇总 | 已实现，执行默认关闭             | 未知交付不重发；采集成功/阈值达标不等于批准                         |
| 历史报告/Word 草稿、同基准复测                           | 已实现                           | 草稿与比较不自动批准、不自动再执行                                  |
| 双盲复核/独立仲裁、评估修订、独立历史报告/复测 Word/PDF  | 候选代码已实现，未部署           | `eval_0010..0012`；旧 owner 路径保持独立                            |
| 授权配置导出与外部技术元数据隔离接收                     | 候选代码已实现，未部署           | `eval_0013..0014`；不接纳敏感输出为可信证据                         |
| 独立本地 QA 命令、共享核心、锁定软件分发、加密输出       | 候选代码已实现                   | 默认离线；真实发送与输出模式分别同意                                |
| 未完成/损坏本地输出的保留治理                            | 加密运行时已接入，管理命令未完成 | 输出前 durable receipt；指定 ID/hash、显式 API 处置；无安全擦除保证 |
| 聊天、私有助手、请求调试、旧定时评测、模型管理           | 兼容入口保留                     | 模型调用需配置与授权；旧调度不代表新 QA 链调度完成                  |

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

- 运行时接入后的最终完整离线回归：**13,393 passed / 77 skipped / 11 deselected / 40 warnings**，791.25s。本地为默认 dev 安装，未安装 PostgreSQL extra 或启动独占 PostgreSQL；相关专项等按原门禁跳过。远端数据库服务门禁单独核验。
- 运行时 CLI/receipt/retention 联合 **210 passed**，含实际软件档案的分发/API 联合 **284 passed**；覆盖输出前 durable receipt、重复取消、真实 module 入口及 receipt/header/首 attempt 硬退出。Blocking IO **72 passed / 2 warnings**，领域 **15 / 58 passed**，完整后端 Ruff check/format **1,280 files** 通过。专项与全量重叠，不相加；基础模块前轮专项与原始失败见交付历史。
- 新鲜六工具 hash-locked build → sdist/wheel → 12 依赖完整离线安装、新 no-system-site venv 中实际 plaintext/encrypted CLI、打开/清理/原 ID 对账与新 retention API 验证通过。当前软件档案 allowlist 为 **37** 个第一方源码成员。

专项、联合和全量有重叠，不相加；skip 不是通过。前端/浏览器历史通过数没有在本轮本地重跑，Linux 验证不代替 Windows 验收。

基线提交 **`5fa993445400feae0420261231d4a6dd1e6d0bee`** 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43549070559)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43549070532)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43549070615)和 [Unit](https://github.com/helloboy829/DevPilot/actions/runs/43549070550)共 **4 workflows / 8 jobs 全成功**，含默认安装全量 collection、带 PostgreSQL 的完整后端、软件分发与实际安装导出。默认 collection 步骤用时 355s；前一提交的 10m 超时没有确证根因，不宣称已修复。一次 60s 有界诊断保持原门禁，没有扩大 timeout 或自动重试。新 retention 运行时模块的 SHA/CI 另行核验，不能沿用基线结果。

原始红灯、修复原因和逐轮收据见[交付历史](DevPilot_Delivery_History.md)。push、本地通过、CI 成功和部署是独立事实。

## 下一步优先级

| 优先级 | 工作                                                   | 退出条件                                                                         |
| ------ | ------------------------------------------------------ | -------------------------------------------------------------------------------- |
| P0     | 当前源码 CI、环境与候选升级验收闭环                    | 精确 SHA 门禁、当前镜像源码核对、数据/配置保护、隔离迁移及回退演练；部署另行执行 |
| P1     | 本地 retention 显式管理命令与残留产物治理              | 复用已接入的输出前 receipt；原 ID/hash、独立处置同意、重复取消及实际安装验证     |
| P1     | 独立版本化正式批准                                     | 固定历史来源、职责分离、审批修订/撤销及用户验收；不能把 case PASS 当批准         |
| P1     | Lost Worker 安全处置与新 QA 调度准入                   | 证明旧 Worker 不能发送后再讨论释放；未知请求绝不重发；不能沿用旧调度绕准入       |
| P2     | 敏感外部证据治理、CV/流式指标/模型裁判、整改与知识闭环 | 各自授权、隔离、证据/计量与人工审查；缺失指标不填零、不判 PASS                   |

开发环境恢复不必等所有 P1/P2 功能完成；正式质量验收依赖独立批准及相应业务能力。具体交付以模块退出条件为准，项目整体尚未完成。

English: Source capabilities, candidate migrations, exact-commit verification and observed runtime are tracked separately. Business containers were stopped at the recorded observation; no deployment or real calls were performed. Encrypted runtime retention receipts are connected; management commands, independent approval and safe lost-worker/scheduling operations remain open.
