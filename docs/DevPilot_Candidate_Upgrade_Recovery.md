# 候选 SQLite 升级与恢复演练 / Candidate upgrade recovery

2026-11-14。本模块补充可重复的合成数据库回归，验证本地 SQLite 的 `eval_0009 → eval_0014` 及升级前备份恢复。测试代码位于 `backend/tests/test_candidate_upgrade_recovery.py`，复用真实迁移、仓库、密码校验和历史 Word 渲染；没有新增运行时迁移命令或业务恢复工具。

## 运行

使用项目 Python 3.12 与锁文件环境，从仓库根目录执行：

```sh
cd backend
uv sync --frozen --group dev
uv run pytest tests/test_candidate_upgrade_recovery.py -q -s --tb=short
```

测试只创建 pytest 临时路径，不接受现有数据库、配置或备份路径，不读取私有配置。合成账号、密码、key、输入、金标和输出只用于临时数据库；DNS/socket 发送被拒绝，不调用目标、模型或 Gateway。完整回归仍使用原 `make test`、`make test-blocking-io` 和 `make lint`。

联合迁移验证：

```sh
uv run pytest tests/test_candidate_upgrade_recovery.py \
  tests/test_review_tasks_migrations.py tests/test_qa_assessments_migrations.py \
  tests/test_qa_independent_archives_migrations.py \
  tests/test_authorized_qa_exports_migrations.py \
  tests/test_external_qa_quarantine_migrations.py -q --tb=short
```

这些已有专项的 PostgreSQL cases 需要独占服务器及 `--extra postgres`，未配置时仍按原条件 skip；SQLite 演练不冒充 PostgreSQL 原生备份恢复验收。

## 合成数据与版本矩阵

起点使用真实 Harness bootstrap、真实 `alembic_version` 和 App `eval_0009`，没有手写假的 Harness revision。三个账号覆盖 admin/user、needs_setup、token_version 和可由真实密码函数校验的 hash。两个历史 QA run 保留每次 **ALL 2** 个冻结样本、请求版本/计划/hash、密文输出、人工复核、不可变报告和同基准复测。

当前合成起点共 **39 张表**；每阶段对所有旧表（包括空表）、所有行和旧表 SQL 定义/索引做完整快照比较，并运行 SQLite `integrity_check` / `foreign_key_check`。只有 App revision ledger 可按阶段变更，Harness ledger 必须不变；新增表必须与固定合同集合完全一致。

| App revision | 合成表数 | 新增职责                                    |
| ------------ | -------: | ------------------------------------------- |
| `eval_0009`  |       39 | 升级前冻结来源、证据、旧报告/复测及 Harness |
| `eval_0010`  |       44 | 五张独立 case 复核表                        |
| `eval_0011`  |       45 | 独立评估修订                                |
| `eval_0012`  |       47 | 独立报告/复测档案                           |
| `eval_0013`  |       49 | 授权导出与审计                              |
| `eval_0014`  |       51 | 外部技术隔离接收与审计                      |

分别执行逐级升级、直接升级 head 及 head 重复 no-op。升级后与还原后的新连接实际读取旧报告/复测、解密合成 case、校验 ALL 分母与账号密码，并比较历史 Word 字节；不只比较表存在性或文件 hash。

恢复读取复用测试进程内明确生成并保留的合成 request/evidence key；不从备份数据库推导 key，没有验证生产密钥备份、私有配置、文件权限/挂载或完整旧镜像的运行兼容性。真实登录/JWT/RBAC 与浏览器链路由独立回归负责，此处只证明恢复后的账号字段和密码函数校验。

## WAL、失败与恢复边界

演练持有 idle WAL anchor，关闭自动 checkpoint；显式 checkpoint 后再提交一次账号 token_version 变更，确保它只在 WAL。只复制主 `.db` 的反例必须漏掉这次已提交变更，完整快照验证必须拒绝；SQLite online backup 则必须保留。备份目标独占创建，已有目标拒绝覆盖，完成后 fsync。

升级始终作用于合成候选副本。还原从已验证的升级前备份写入**另一个新路径**，要求全部旧 schema/行与升级前相同、备份 hash 不变。另在 `eval_0011` 已实际提交后注入“结果丢失”，保留失败候选，只验证独立还原，不在不确定库上重跑、修复或试 downgrade。

七类历史行丢失（账号、组件、数据集、输出密文、报告、复测、Harness ledger）与空表丢失/旧表列变化都使用各自新副本，验证快照或完整性检查确实拒绝，避免“检查器总是通过”。本模块是验证新增，不宣称发现或修复了原迁移的运行时缺陷。

**恢复升级前备份会丢弃备份后的新写入。** 回归专门在候选库增加一次账号版本更新，再验证还原回到备份时刻；这不是无损回退、自动合并或旧镜像可直接兼容新 schema 的证明。实际操作仍需停写/在途请求治理、明确恢复点、可恢复备份、配置与挂载核对；这些没有在业务环境执行。

## 验证与后续

`-s` 输出两份 `synthetic-qa-upgrade-recovery.v1` JSON，仅包含合成版本/表数/hash/验证状态；随机合成身份、密文和密码盐使不同次执行 hash 可不同。hash 不认证来源、执行权限或正式批准。逐轮计数、精确 SHA/CI 和隔离资源收尾见[当前状态](DevPilot_Delivery_Status.md)与[历史](DevPilot_Delivery_History.md)。

本轮没有修改依赖、迁移、App/API、业务配置或执行开关。候选镜像源码核对、浏览器/真实账号验收、PostgreSQL 原生备份恢复、Windows 和正式批准仍独立进行；本机业务库/卷没有被复制、迁移或还原，业务容器仍按实际观察记录状态。

English: Synthetic SQLite rehearsal exercises the real eval_0009-to-eval_0014 chain, WAL-aware backup and restore to a fresh old-schema database. All historical tables/rows/schema, accounts, encrypted cases, reports, retests and Word bytes are verified. A committed-but-unconfirmed migration is retained rather than repaired. Restoring an earlier backup loses later writes; this is neither a production recovery tool nor deployment, PostgreSQL/Windows acceptance or formal approval.
