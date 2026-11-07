# DevPilot 耐久派发日志：技术元数据切片

更新：2026-11-08。实现：

- `backend/app/evaluation/dispatch_journal.py`（内部仓库）；
- `backend/app/evaluation/migrations/versions/eval_0005.py`（App 增量迁移）；
- `backend/tests/test_dispatch_journal.py`（纯合成数据测试）。

## 1. 目的与定位

在目标请求真正发送之前，可靠记录“这一条可能会被发送”；进程中断或数据库写入结果不确定后，不能把它重新当成未发送数据。它为后续独立执行准入和 Worker 提供持久技术状态，**本身既不是执行许可，也不启动网络请求**。

范围固定为 `dispatch_journal_only`。现有冻结计划界面、手动测试和定时路径没有切换到本日志；没有新增 HTTP API、后台循环、Agent 工具或模型依赖。技术采集结束不代表效果通过，日志也不保存完整输出证据。

## 2. 已实现的数据流

1. `record_run` 校验 owner/project、计划 schema/hash、冻结 QA revision/hash 和样本 ID 数量；依照 Python 字符串排序的 sample_id 固定 ordinal 和循环样本顺序。只读取元数据和样本 ID，不读取问题、金标、请求密文，不解密。
2. 未来已独立授权的调用方必须先成功提交 `record_dispatch`，再进行至多一次请求发送。每个 ordinal 只能从 pending 派发一次；不提供 reset/requeue/resend。
3. 同一运行的数据库行写锁串行化变更；并发槽位、累计请求正文字节、累计响应留存预留与派发标记在同一事务提交。事务不跨网络、解密或模型 I/O。
4. 派发票据绑定运行、序号、样本和租约，随机 token 不进入 repr，数据库只保存其 SHA-256。公共元数据查询不选择 token hash；票据不构成目标授权。
5. `record_observation` 仅接受严格、有限的技术字段：类别、HTTP 状态、留存字节和总耗时；拒绝输出正文、PASS/准确率、TTFT、NaN/Inf 和布尔计数。有效租约和 token 校验后只写一次。
6. 每次变更与审计同事务；审计按运行内单调 sequence 排序，同一毫秒也不依赖随机 UUID 顺序。数据库写入/提交不确定统一抛出 `JournalWriteUnconfirmed`，不返回票据，不泄露 SQL/底层错误；读取状态不是自动发送或重试许可。

## 3. 预算与终态

- 沿用冻结计划的请求数、并发、单次时限、运行总时限及请求正文预算；最多 10,000 次、64 并发。这里只做内部日志约束，不能替代跨运行/账号的全局资源配额。
- 每次派发预留 `max_response_bytes + 1` 字节，额外一字节用于检测响应超限。响应总留存预算最多 67,108,864 字节，预留**不回收**，即使实际响应短或技术失败也不释放预算。
- 这里的字节不是 socket 总流量、headers、HTTPX 预读、计费 token 或账单配额；请求正文长度由未来受信调用方准确提供，日志不会自行渲染验证。
- 租约截止取单次超时＋宽限与运行截止的较早者。过期派发会阻止继续预留；显式过期处理将**整次运行**中断，不回收可能仍活跃的槽位继续原运行。尚无后台 reaper 自动调用它。
- 中断保留已记录观测；已派发且未确认的行变为 `delivery_unknown`，未派发变为 `not_dispatched`。取消和终态操作幂等，不改写已完成技术记录，不提供恢复发送。
- 所有 ordinal 已记录技术结果后为 `recording_finished`；这不是效果 PASS、质量判决、完整响应存证或可直接引用的报告证据。未知派发会中断整次运行。

## 4. 数据库兼容与隔离

App ledger 从 eval_0004 追加到 **eval_0005**；仅新增 evaluation_dispatch_runs、evaluation_dispatches、evaluation_dispatch_audit 三表及状态/租约复合索引。旧迁移不修改，Harness metadata 与 alembic_version 不修改。所有读取和写入保持 owner/project 隔离。

升级测试从真实 eval_0004 schema 开始种合成项目、请求与 QA 计划，并保留合成用户和 Harness ledger；升级两次后比较旧表完整行与外键完整性。SQLite 已验证；尚未进行真实 PostgreSQL 环境验收，不把两连接测试描述为跨数据库验证。

## 5. 验证记录

先写测试并实际观察到缺模块失败；实现后测试发现重复取消导致 revision 变化，修复并补幂等回归。新增索引测试也先观察失败，再补 metadata 与新迁移中的索引。

当前新增 **67 项离线测试通过**，包括两个独立 OS 子进程竞争有限响应预算、双连接并发/重复 ordinal、进程重建后防重发、租约/截止/取消、审计事务回滚、已提交但连接失联的不确定写入、脱敏错误、严格 DTO、无金标/密文/输入读取与旧库升级保留。

首轮完整后端回归为 11,749 passed / 3 failed / 73 skipped，三个失败均为旧测试仍断言最新 head=eval_0004；只修复最新版本断言，保留历史升级起点和全部数据保留检查后重跑。修复后完整后端回归 **11,752 passed / 73 skipped / 39 warnings**，领域 unittest **15 + 58 通过**，backend Ruff lint 与 1,187 个文件的格式检查通过。同 SHA Actions 在推送后按完整提交另行核对；没有触发的工作流不计通过。测试计数仅为工程合成回归，不含客户历史业务指标；未调用真实组件或付费模型。

离线复现（先按 backend 指南安装依赖，在 backend 目录运行）：

```bash
PYTHONPATH=. uv run pytest -q tests/test_dispatch_journal.py tests/test_evaluation_datasets.py tests/test_evaluation_registry.py tests/test_evaluation_plans.py tests/test_request_version_repository.py
make test
make lint
```

## 6. 仍需继续开发

1. 独立运行准入：用户权限、目标授权和重新确认、请求/QA 内容重验、全局资源预算、独立执行同意。
2. 有界 Worker：在准入、派发提交之后调用现有单次采集器；取消/宕机只做保守终止，绝不自动重发未知请求。
3. 加密且不可变的逐条输出存证、来源关联、受控读取与保留/删除策略。
4. 人工复核：同屏组件版本、Q、实际 A、预期/容差、来源与技术状态；领取、理由、仲裁、审计及稳定分母。
5. 报告引用持久结果与模板修订；后续再接调度、CV 和独立脚本导出。

不能把“有派发日志”或“冻结了计划”当作完整自动化评测已交付。

## 7. 本地增量更新与保留检查

在 SQLite 在线备份及 integrity_check 通过后，仅更新本切片 Gateway 镜像；Frontend 没有源码变化，保留上一轮已更新版本。实际核验原账号完整行、全部旧评测行、配置 hash 与挂载均保留，Harness ledger 不变；App ledger 从 eval_0004 正常追加到 eval_0005，三个新日志表仍为空，没有自动创建业务运行。无关容器及 Frontend 身份保留，三份部署源文件 hash 一致。

全部现有账号的只读浏览器验烟通过：个人助手、无模型手动配置、五套风格、请求版本元数据和冻结计划入口；没有模型调用、保存助手或业务数据写入。当前工作模型和独立请求加密密钥仍未配置，未擅自生成；不能据此宣称真实组件调用、真实计划创建或自动评测已验收。
