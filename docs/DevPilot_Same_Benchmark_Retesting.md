# 同基准整改复测 / Same-benchmark retesting

> 2026-11-08：实现范围为已完成人工复核的 QA JSON 效果运行比较和不可变存档。不是全平台完成，不自动执行复测或批准验收。App `eval_0009` 已经在线一致性备份后升级并独立核验，功能提交 `3a5cd38fc99d84160d8abc59ce446a77d26605f7` 的六项 Actions 均成功；本地收据不入 Git。真实模型/目标验收仍未进行。

## 业务用途

在 `/workspace/retests`（侧栏“整改复测”）显式加载项目和已有运行，选择基准运行及整改后运行。先加载服务器验证过的人工汇总，再单独勾选确认、保存。指标不允许手填或由 Agent 生成后直接认定为平台结果。

每条样本展示：样本 ID、修复/退化/保持通过/仍未通过；可筛选后显式打开两侧输入 Q、预期结果和输出 A。Q/A 不进入比较列表或存档，只有拥有项目并具有人工复核权限的人显式打开时才读取。当前复核版本可以比存档版本新，界面同时标注，两者不混称。

## 可比较性门槛

- 同一所有者、项目、组件；两个不同运行、两个不同冻结计划及不同规范化版本标签。
- 复测开始时间必须严格晚于基准运行结束时间，不能以并行运行冒充整改先后关系。
- 同一冻结数据集 ID、修订号、哈希、用途（baseline / acceptance）和全部样本顺序。
- JSON 映射、响应模式、效果判定政策、请求数、并发、超时、总时限及请求/响应预算、预检完全一致。
- 两边采集正常结束、每个冻结样本都有验证输出证据，最新人工决定全部为 pass 或 fail；未复核、待确认、技术不完整和性能重复请求不能作为完整复测存档。
- 接口/请求版本允许变化，会显示“请求定义不同”；接口不变但供应方模型升级也可复测。计划版本标签是人的声明，不是对供应方实际模型版本的独立认证。
- 更换数据集或口径应另作独立评测，不得宣称为可直接比较的提升。

## 统计与版本

仅服务器统计每条样本的 fail→pass、pass→fail、pass→pass、fail→fail。人工通过率＝最新人工通过数 / **全部冻结样本数**。差值保存整数分子和相同分母，界面显示百分点（pp），不平均跨组件、不混入 TTFT/TPS/性能结果。

每对运行最多一个档案；要记录新一轮整改应产生新运行及新版本标签。后续复核、模板或配置变化不改写历史比较。比较档案保存两侧汇总、基准指纹、样本判定及版本承诺、差值和收据，不复制 Q/A、参考答案、人工备注、凭据或请求体。收据是完整性哈希，不是数字签名，也不防有权同时改写数据库及所有哈希的管理员。

状态固定为 `not_approved`。即使全通过，也不能在尚无冻结/批准验收标准时自动标记项目验收通过。

## 安全、持久化与未知写入

API：`GET /api/evaluation/projects/{project_id}/retest-archives`（最近 100 条元数据）、`GET/PUT .../retest-archives/{32hex_id}`。无更新、删除、自动调用目标或通知路由。

所有路由要求登录、项目所有权、read + review；PUT 另需 write，内部 Agent 不得代替人工。响应及私密校验失败使用 private/no-store，不回显输入或 SQL。现有共享认证/CSRF 入口不变。

1. 客户端只提交两侧 run ID、已查看汇总哈希和显式布尔确认，不提交指标。
2. 服务器读取完整冻结源，在工作线程验证数据、加密证据和最新人工决定。
3. 最终事务锁项目，再按 run ID 顺序锁两个运行并重读全部快照；任何并发复核/来源变化都拒绝存档。
4. 比较档案与两个运行的 `retest_archived` 审计原子追加，失败一起回滚。
5. 同 ID、同请求返回原收据；同 ID 不同请求冲突。数据库故障视为写入未知，不能自动重发或换 ID。
6. 前端在发送前保留待定 ID，切换项目后仍可核对；只能同 ID GET 找回收据。404/故障不证明原请求永不会提交，因此不自动解锁重发。没有后台重试或浏览器持久化；离开页面前保留 ID，重开页面可手填 ID 读取历史记录。
7. 项目切换、卸载、选择变化、筛选及操作会清空或隔离敏感视图；迟到响应不得进入新项目。

迁移 `eval_0009` 只追加 App-owned `evaluation_retest_archives` 及约束/索引，沿用单独 ledger，不更改 Harness `alembic_version`、账号及旧数据。部署前在线备份并校验，禁止删卷重建。

## 测试与未包含范围

后端以全合成数据覆盖：正向修复/退化、固定分母、同基准不一致、同运行/计划/方向、最新复核竞争、两侧锁序、原子回滚、哈希篡改、幂等、所有权、权限、私密错误及重复升级保留旧数据/报告/Harness ledger。前端 DOM 覆盖：显式动作、确认失效、未知写入同 ID 核对、跨项目迟到隔离和 Q/A 按需打开；浏览器用合成 API 模拟桌面和窄屏。

测试不是实际目标或模型联调，不是性能压测或最终用户验收。后续仍需独立的整改工单/通知、验收标准与批准、评测调度准入、CV、流式性能指标和可独立执行脚本导出。报告 Agent 可读取授权的结构化材料提出解释，但本切片没有新增 Agent 调用或授予其人工批准权。

## English summary

The retesting workspace archives one immutable comparison per pair of fully human-reviewed QA effectiveness runs. It enforces the same owner/project/component, frozen dataset, mapping, policy and execution budgets; a distinct declared plan version; and retest start after baseline completion. Requests may change, but supplier version identity is not independently attested. Server-derived per-sample transitions and fixed-denominator human pass-rate deltas never imply acceptance.

Only authenticated project owners with read/review access may read; writes also require write access and explicit human confirmation. Crypto validation runs off-loop; ordered final locks reject changed snapshots. Both run audit entries and the append are atomic. Unknown writes reconcile the same ID by GET only; never automatically resend or mint a replacement ID. History survives later reviews without copying raw Q/A into comparison metadata. On-demand paired evidence is separately authorized and shows frozen versus current revision boundaries. Additive `eval_0009` preserves prior data and the Harness ledger. Synthetic tests do not establish live model/target validation or platform completion.
