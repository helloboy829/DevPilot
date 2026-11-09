# 独立 QA 主链离线集成回归 / Independent QA workflow regression

日期 / Date：2026-11-09。状态：候选代码的合成回归，不是部署、多账号浏览器验收或正式批准。

## 范围与实现

新增 `backend/tests/test_qa_independent_workflow_api.py`，复用 `test_qa_workflow_api.py` 的隔离 fixture 和真实 `QAExecutionWorker`。从 HTTP 创建冻结 QA、加密请求版本、v2 计划和执行收据开始，不通过 repository/SQL 插入计划、输出、任务、决定、评估或档案以跳过服务边界。

- 临时 SQLite 由独立 App Alembic 迁移；账号、三个问答样本、密钥、请求和响应全部合成。没有复制账号数据库、私有配置或真实参考答案。
- 合成认证 middleware 切换 owner、两名盲审人、仲裁人和无关账号；账号查找仅替换为固定合成人类 UUID，不增加目录或项目成员权限。这不是部署认证验收。
- 仅替换 DNS 和 HTTP wire；保留共享 DNS-pinned transport、冻结请求渲染、逐样本持久派发、配额和 Worker。独立 DB session 在 wire 前确认 dispatch 已提交；原始 socket 连接/发送和非预期 DNS fail closed，transport `retries=0`。
- 测试专用 `ExecutionPolicy(enabled=True)` 只存在于 fixture；不会设置运行开关、生成生产 key、调用真实模型/目标或部署迁移。

## 固定断言

1. **真实两版本链**：并发 1/2，先保存两个请求版本，再执行 v1/v2；冻结请求不可替换成 latest。两次运行各三个样本，冻结时钟显式递增，不用 sleep 证明先后。
2. **独立性与隐私**：owner 全 PASS 不进入独立计数；两名 reviewer 明确 claim/open 后投票且看不到对方投票；分歧只能交第三名仲裁人。单条授权不能打开 owner 的数据集、源案例、评估或档案，无关账号不能读取任务。普通元数据、错误、Word 和日志不能包含合成 Q/A/gold/备注/请求秘密；显式案例打开、仲裁材料和 owner 结果打开按既有合同属于敏感响应，结果备注被明确核对，不误称元数据。
3. **全分母与标准**：三条冻结样本始终进入分母；2/3 在 6667 basis points 下为 `not_met`，3/3 为 `met`，都为 `not_approved`。独立投票不改写旧 owner summary，独立报告/复测不填入旧档案命名空间。
4. **历史不可变**：显式保存 assessment ID/修订/hash，再归档报告、导出固定 Word、建立同基准复测。重开 baseline 任务后，新评估变 provisional，不可作为完整来源；旧轮次/评估/报告/复测仍可按 ID 打开，完整历史来源仍可显式选择。相同 assessment 对不能用新 ID 重复比较；不同明确修订仍受历史来源合同约束。
5. **不依赖当前状态导出**：删除测试 key 并禁止当前模板/来源读取后，历史档案和 Word 字节仍相同；敏感源打开则安全失败。Word 只含保存的 Markdown/公共收据，不重算指标。
6. **六种采集故障**：HTTP 错误、非法输出、响应限额、不支持的响应、未知交付和出站策略拒绝。缺少输出不能 PASS，独立 uncertain 和技术缺口阻塞完整性，即使标准为零；未派发样本不从分母消失。只发生允许的一次发送，Worker 不继续重发。
7. **未知写入**：分别在 task / assessment / report / retest 写入的 ASGI 提交前或提交成功后丢失 HTTP 响应。调用方只 GET 同一 ID；即使 404 也不再次写入，不换 ID，不新增 dispatch。此测试是客户端边界的合成故障；既有 router/repository 回归另行覆盖 DB 不确定提交和原子审计。

合计 16 个参数化用例（2 个正常并发、6 个故障、8 个未知响应），与既有单元/接口测试互补，不把重复覆盖相加为独立验收数量。

## 验证命令与记录

隔离 Linux Python 3.12 环境从跟踪源码与冻结 lockfiles 构建，复用上一模块已核实且停止的专用依赖容器。仅启动本轮需要的 Python、合成 PostgreSQL/Redis；Node 容器仅在文档格式检查时启动。无业务挂载/宿主端口，测试网络为 internal。执行记录和成功/失败日志放在 ignored `.deer-flow/ci/20261109-independent-workflow/`，不进入 Git。

```sh
cd backend
PYTHONPATH=. uv run pytest tests/test_qa_independent_workflow_api.py -q --tb=short
make test
make test-blocking-io
make lint
# 在 frontend 中执行文档格式检查；没有前端运行时代码变更。
node node_modules/prettier/bin/prettier.cjs --check ../docs/DevPilot_Independent_Workflow_Regression.md
```

本地结果：定向 **16 passed / 44.11s**；标准后端 **12,339 passed / 18 skipped / 11 deselected / 40 warnings / 606.06s**，纯领域 **15 / 58 passed**；独立 Blocking IO **72 passed / 5.50s**；Ruff check/format **1,241 文件**、整个前端 Prettier 及本轮 Markdown 格式检查通过。实际 Python 测试快照的 **2,178** 个公开文件逐项 hash 一致。前端单测/build/浏览器未在本测试专用模块本地重跑；上一模块结果不算新模块的 CI。

精确提交/Actions 收据与资源收尾记录见 [交付矩阵](DevPilot_Delivery_Status.md)。编写阶段的邮箱校验、敏感 DTO 形状/结果备注和比较唯一性断言错误保留日志，按既有合同修正测试；不增加超时/重试、不放宽业务规则或删除故障检查。

## 不包含与回退

无运行时代码、迁移、依赖、生产配置、权限政策、自动调度或部署变更。不是独立 pre-run admission、真实身份认证验收、形式化证明或平台最终完成。独立复测 Word/PDF、正式批准、经授权的保留数据升级和真实多账号验收仍需单独模块与批准。回退仅撤销该测试及文档，不修改已部署 ledger、数据或历史 renderer。

## English summary

Sixteen synthetic integration cases exercise HTTP-created frozen v2 plans through the real bounded Worker, blind human task APIs, separate arbitration, immutable assessment revisions and explicitly selected historical report/retest archives, including the pinned independent Word export. DNS/wire are substituted with sockets fail-closed; dispatch commit is observed before I/O. All three frozen samples remain in every denominator. Owner votes never substitute for independent decisions, missing evidence cannot PASS, zero thresholds do not bypass completeness, and `met` is not approval.

Reopened tasks do not rewrite archived revisions. Unknown task/assessment/report/retest HTTP outcomes reconcile only by GET of the same ID, including 404, with no automatic resend or replacement ID. Sensitive case/result opens remain explicit; ordinary metadata, exports and logs are checked for synthetic secret canaries. This test-only module adds no runtime feature, dependency, migration, production enablement, model/target call or deployment, and does not replace real authentication/browser/operational acceptance.
