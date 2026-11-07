# CI 修复与隔离开发环境

> 2026-11-07。仅记录本轮已执行的工程验证；不等于生产部署验收、真实组件效果验收或安全整改全部完成。不会改 Conda base，也不操作现有业务容器。

## 1. 真实失败原因

核查 GitHub 仓库 helloboy829/DevPilot 两次提交的实际 job 日志，而不是根据邮件猜测：b7f930a4669713125c116350af331679d7577bfa、5c43303d383097fb4fa3cbd74905d4d002d0aa34。

| Workflow | 失败点 | 修复方式 |
| --- | --- | --- |
| Unit Tests | 1 项文档清理回归仍读取 3 份已移除的历史文档；9 项迁移/并发回归写死旧 head 0011_mcp_tasks | 改为校验当前维护的入口/架构/部署文档；历史 seed 仍保持原迁移，最终 head 使用实际迁移链；中央测试保留明确 head pin，新增迁移幂等/旧库升级回归 |
| Frontend Unit Tests | 文档 layout 文件缺失，样式隔离回归无法读取 | 恢复英文/中文 docs layout 与 MDX catch-all 路由，增加 page-map 和语言/路径边界测试 |
| E2E Tests | 文档页面 404，4 个卡片/Markdown/反馈编辑链接用例失败 | 恢复路由与本地化 page map；编辑和反馈指向当前 fork；保留原测试，新增不支持路径 404 回归 |
| Lint Check | 4 个前端文件不符合 Prettier 格式，后续检查尚未执行 | 按锁定依赖格式化；继续执行 ESLint、TypeScript、生产构建，不以关闭检查修复 |

本地完整基线还暴露一个离线单测依赖真实 DNS：Crawl4AI HTTP client 已 mock，但 URL 安全检查仍解析 example.com。在测试中 mock 公网 DNS 地址，并新增无法解析主机的拒绝回归；保留私网/元数据地址拒绝测试，生产 URL 安全逻辑不改。

两个原提交均有相同 CI 失败；此次修复尚须新提交的远端运行确认，不能用本地通过替代 Actions 结果。

## 2. 本轮使用的隔离环境

| 用途 | 环境 |
| --- | --- |
| 后端 | python:3.12-bookworm，实际 Python 3.12.16，uv 0.13.7；uv.lock 冻结安装 dev + postgres；Ruff 0.15.12 |
| 前端 | node:22-bookworm，实际 Node 22.23.4、pnpm 10.26.2；frozen-lockfile；Playwright Chromium |
| 集成服务 | postgres:17、redis:7-alpine，专用 devpilot-ci 网络，不发布宿主端口 |
| 代码 | 受控源码快照复制到容器 /workspace；不是宿主目录挂载，不带密钥/运行配置/客户原件 |

容器名 devpilot-ci-python、devpilot-ci-node、devpilot-ci-postgres、devpilot-ci-redis。无 Docker socket 挂载、无宿主端口发布；不与既有业务服务共享数据卷。测试镜像/依赖下载需要网络，测试不调用用户材料中的目标接口。完整后端部分集成用例仅访问隔离测试服务。

镜像 digest（本轮实际拉取，仅用于复现，不承诺将来标签不变）：

- Python: sha256:4209fae09a3e20afd863e528bfddc235da5fd5977983e1996cd54cc9a72e6267
- Node: sha256:7702d8aa4d5910871692af4480eb3ba86f23047a6417a44d857d06c95d060d3f
- PostgreSQL: sha256:748a18a54d3842d43bc156f0840d78029b8d349e0feca98c12b9c4ce3404a6b3
- Redis: sha256:c5d34a98396a4775e223c74e929162c35c5a2182901ba26b50ade939941ce14b

Conda 可用于另建指定 Python 版本的环境，但不与 Docker 环境叠加作为必需步骤；本轮以更接近 CI 的 Linux Docker 环境为准，未修改宿主 base。该环境不是项目的生产镜像。

## 3. 可复现操作

以下是手动复现步骤，不是自动创建脚本。仅在容器名未占用时创建，重复执行前先检查已有资源；不要删除其他容器或执行全局 prune。PowerShell 在仓库根目录执行：

~~~powershell
# 先提交需要验证的源码，再导出 HEAD；不要打包工作区全部文件。
$archive = Join-Path $env:TEMP 'devpilot-ci-source.tar'
git archive --format=tar --output=$archive HEAD

docker run -d --name devpilot-ci-python --cpus 3 --memory 4g -w /workspace python:3.12-bookworm sleep infinity
docker run -d --name devpilot-ci-node --cpus 4 --memory 6g -w /workspace/frontend node:22-bookworm sleep infinity
docker cp $archive devpilot-ci-python:/tmp/source.tar
docker cp $archive devpilot-ci-node:/tmp/source.tar
docker exec devpilot-ci-python sh -lc 'tar -xf /tmp/source.tar -C /workspace && git init /workspace'
docker exec devpilot-ci-node sh -lc 'mkdir -p /workspace && tar -xf /tmp/source.tar -C /workspace && git init /workspace'
# .git 标识供静态检测器定位仓库；没有标识时测试会拒绝猜根目录。
docker exec devpilot-ci-python sh -lc 'python -m pip install uv==0.13.7 && cd /workspace/backend && uv sync --frozen --group dev --extra postgres'
docker exec devpilot-ci-node sh -lc 'apt-get update && apt-get install -y python3 && corepack enable && corepack prepare pnpm@10.26.2 --activate && cd /workspace/frontend && python3 /workspace/scripts/pnpm.py install --frozen-lockfile && python3 /workspace/scripts/pnpm.py exec playwright install chromium --with-deps'
~~~

测试服务（以下密码只是一次性隔离测试值，不能用于部署）：

~~~powershell
docker network create devpilot-ci
docker network connect devpilot-ci devpilot-ci-python
docker run -d --name devpilot-ci-postgres --network devpilot-ci -e POSTGRES_USER=deerflow -e POSTGRES_PASSWORD=ci-local-only -e POSTGRES_DB=deerflow_test postgres:17
docker run -d --name devpilot-ci-redis --network devpilot-ci redis:7-alpine
docker exec devpilot-ci-postgres pg_isready -U deerflow -d deerflow_test
docker exec devpilot-ci-redis redis-cli ping
~~~

确认服务 ready 后：

~~~powershell
docker exec devpilot-ci-python sh -lc 'cd /workspace/backend && make lint && TEST_POSTGRES_URI=postgresql://deerflow:ci-local-only@devpilot-ci-postgres:5432/deerflow_test?sslmode=disable DEDUPE_TEST_POSTGRES_URL=postgresql://deerflow:ci-local-only@devpilot-ci-postgres:5432/deerflow_test?sslmode=disable DEER_FLOW_TEST_REDIS_URL=redis://devpilot-ci-redis:6379/15 make test'
docker exec devpilot-ci-node sh -lc 'cd /workspace/frontend && python3 /workspace/scripts/pnpm.py format && python3 /workspace/scripts/pnpm.py check && python3 /workspace/scripts/pnpm.py test && BETTER_AUTH_SECRET=local-dev-secret python3 /workspace/scripts/pnpm.py build'
docker exec devpilot-ci-node sh -lc 'cd /workspace/frontend && CI=1 SKIP_ENV_VALIDATION=1 python3 /workspace/scripts/pnpm.py exec playwright test --reporter=line && CI=1 SKIP_ENV_VALIDATION=1 python3 /workspace/scripts/pnpm.py exec playwright test -c playwright.auth.config.ts --reporter=line'
~~~

本地改动同步容器须精确复制源码，不能从容器整目录反拷 node_modules、.venv 或 .next。测试完成后可 stop 专用测试容器保留依赖缓存；下次 start 恢复。长期不用时只清理这些明确命名的资源，不运行全局清理。

## 4. 本地验证记录

- 修复前完整后端基线：11 failed、11,236 passed、73 skipped；其中 10 项复现远端故障，另 1 项真实 DNS 依赖。首次收集因快照无 .git 失败，补齐标识后重新全量运行，未改变根目录检测器来绕过。
- 修复后 make test：DevPilot evaluation 15 + toolkit 58 = 73 项通过；Gateway pytest **11,294 passed、29 skipped**。跳过是未启用/缺可选运行条件，不把 skipped 算 passed；不是真实目标调用验收。
- 单独 PostgreSQL checkpoint/跨 Pod 去重及 Redis admission：**25 passed**，确认已连接专用服务而非仅跳过。
- 后端 make lint：Ruff check 与 format --check 全通过（1,127 个 Python 文件格式符合）。
- 前端最终验证：Prettier、ESLint、TypeScript 全通过；125 个单测文件、976 项测试通过；完整 E2E **141 passed**，认证恢复 E2E **2 passed**；E2E 启动前均完成生产构建。首轮曾出现 138 passed + 1 flaky（重试后通过），最终一轮无 flaky，仍保留首次抖动事实，不保证以后没有环境抖动。E2E 使用 mock 后端，不代表真实端到端目标 API 已验收。

## 5. 尚未完成的业务与工程门禁

生产 Docker 打包 devpilot 依赖、TLS/凭据/出站策略、耐久任务/取消/资源上限、逐请求性能证据、真实报告导出和完整评测 UI 均需继续按审计清单开发。不能因为 CI 修绿就宣布产品已可正式无人值守验收。

## 6. 脱敏提交远端验证（2026-11-07）

已替换未推送的含敏感分析内容提交，再正常推送 `15adab94215c3ca788d47bbc3f36c3b74c415405`；没有 force push 远端。分析文档公开版删除项目场景名称及原始汇总测试指标，只保留通用设计结论。此处是从待上传分支祖先链移除，不代表本地 Git 对象/reflog 已物理销毁。

通过 GitHub Actions REST API 核对该提交：Unit Tests、E2E Tests、Frontend Unit Tests、Lint Check、Replay E2E (front-back contract)、Backend Blocking IO **全部 completed/success**。该记录仅指这个提交，不替代后续新提交的 CI 状态。

## 7. 报告切片回归说明（2026-11-07）

开发前完整基线：DevPilot 73 项 + Gateway 11,294 passed/29 skipped。报告核心与路由专项 **41 项通过**；报告、浏览器路由及浏览器工具合并专项 **114 passed、1 skipped**。

最终工作区代码的隔离验证：

- 后端 `make test`：DevPilot **73 项通过**，Gateway **11,336 passed、29 skipped**。跳过不计入通过；不是真实客户目标验收。
- Python：全后端 Ruff check、format --check（1,130 文件），新增纯领域 reporting 的 Ruff/格式检查及 `uv lock --check` 全通过。
- 前端：ESLint/TypeScript 通过；**127 个单测文件、984 项测试通过**；本轮报告文件 Prettier 检查通过。
- 完整 Playwright：**147 passed、1 flaky**，共 148 项；新增报告页 **7 项均首轮通过**。Lark 集成旧用例等待弹窗从 `about:blank` 跳转时超时，重试后通过，不记为稳定首过，也没有删除或放宽该断言。
- 独立认证 Playwright：**2 passed**。完整与认证浏览器回归均在启动前完成生产构建，使用 mock 后端，不代表真实平台全栈/客户接口已验收。日志中的 mock 未覆盖轮询访问本地不存在的 Gateway 会出现代理连接拒绝，不将其当作已验证真实后端。

过程中的失败与修复也予保留：第一轮完整后端 1 failed、11,334 passed、29 skipped，第二轮 1 failed、11,335 passed、29 skipped，分别暴露 browser router 和 browser tool 单测依赖真实公网 DNS。仅在模拟浏览器的测试中 stub 解析器，保留生产 URL 安全校验，并增加私网 DNS/解析失败拒绝回归；最终完整回归通过。第一轮完整浏览器 2 failed、141 passed、1 flaky，两个报告断言误匹配 Next route-announcer，已收紧到具体错误文本。

本节记录本地隔离验证，不复用第 6 节旧提交的远端成功结论；新提交的 Actions 必须按其实际 SHA 另行核对。报告目前仍是无状态人工草稿，没有服务端报告历史、正式审批、模板上传编辑或 DOCX/PDF 导出。

## 8. 报告 Agent 切片回归（2026-11-07）

开发前完整基线：DevPilot 73 项通过，Gateway 11,336 passed、29 skipped。本次模型测试仅使用合成输入与假模型运行真实的无工具 LangChain/LangGraph graph，不读取客户原始材料、不调用真实模型或客户接口，不代表生产 provider 的连通性、参数兼容或生成质量已经验收。

最终工作区隔离验证：

- 后端 `make test`：DevPilot evaluation **15** + toolkit **58** = **73 项通过**；Gateway **11,360 passed、29 skipped**（39 warnings）。跳过不算通过。报告、配置、Browserless、fastCRW、Crawl4AI 合并专项 **146 passed**。
- 后端 `make format`、`make lint` 全通过（**1,134** 文件）；纯领域 reporting 的 Ruff/格式与 `uv lock --check` 通过。示例/Helm 配置 YAML 校验及配置门禁通过：同为版本 **34**，报告 Agent 默认关闭，未声明模型时不回退到首个模型。
- 前端全量 Prettier、ESLint/TypeScript 通过；**127 个单测文件、986 项测试通过**。最终完整 Playwright **151 passed、无 flaky**；独立认证回归 **2 passed**。两套 E2E 分开执行，均先完成生产构建；E2E 使用 mock 后端，日志中未被 mock 的后台轮询仍可出现本地不存在 Gateway 的连接拒绝，不将它当作真实全栈验收。
- 已逐文件对比本地和隔离容器源码 SHA256，确认运行时、测试及配置文件与完成验证的版本一致；没有从容器整目录反拷依赖或构建产物。

保留过程失败事实：首次全量后端 **1 failed、11,355 passed、29 skipped**，fastCRW 模拟客户端仍依赖真实 DNS；修复后一轮 **11,359 passed、29 skipped**。最终同步后的再次回归 **1 failed、11,358 passed、29 skipped**，发现 Browserless 相同的 DNS 依赖。仅测试中固定合成公共 DNS，保留私网/metadata 拒绝并新增解析失败不得创建客户端回归；Browserless 错误场景也收紧到准确错误及客户端确实被调用，避免 DNS 错误误充目标错误的通过。未改变生产 SSRF 校验。修复后最终完整回归结果见上。

前端中间一轮全量格式检查曾因 AGENTS.md 多余空行失败，已修正并完整重跑；较早 E2E 为 **149 passed、1 flaky**，抖动来自既有 Lark 弹窗用例重试，最终 **151 项首过**，没有删除或放宽旧断言。

本地回归成功不替代新提交的 GitHub Actions。当前仍为无状态未核验 DRAFT 和可选建议附录：尚无持久报告/可信建议来源、正式审批、模板上传或 DOCX/PDF；模型供应商数据策略及参数兼容还需接入后按授权做 smoke test。项目完整自动化评测闭环也仍需按审计清单推进。

## 2026-11-07：模型连接、评测默认首页与报告多轮

环境仍为独立 Docker 副本，宿主只读挂载、Python 3.12 与锁定前端依赖；不修改本地其他项目，不调用真实业务接口或付费模型。测试工作目录为 backend/frontend，前端 pnpm 经 `scripts/pnpm.py`。

最终后端：`PYTHONPATH=.:/workspace/devpilot/src PWD=/workspace/backend UV_NO_SYNC=1 .venv/bin/python -m pytest -q --tb=short -m 'not live' tests/`，**11,372 passed、73 skipped**；未提供全部可选数据库/网络环境，跳过不计通过。纯领域 `unittest discover`：evaluation **15**、toolkit **58**，共 **73** 通过。`ruff check .` 和 `ruff format --check .`（1152 文件）通过；模型/报告专项 **44** 通过。四类协议均通过真实 SDK 本地构造和配置覆盖/角色路由测试，不代表外部端点已连通。

前端 `check`、全量 `format`、生产 `build` 通过；128 个单测文件、**988 项通过**。认证恢复浏览器测试 **2 项通过**。普通浏览器回归最终结果补充于下方。

过程记录：修改前副本曾出现 uv 离线重装、PWD 环境缺失及一个 teardown 时序失败；规范副本测试环境后未复现。中间全量采集发现模型配置文件重构遗漏 catalog runtime helper，已恢复并新增四协议覆盖/角色路由测试，最终全量通过。前端首次内置 webServer 120 秒等待超时，改为先单独生产构建再启动同一构建测试，不修改仓库超时或跳过用例。第一次完整浏览器为 156 passed、2 failed：旧 landing 仍断言聊天默认路由、新测试的原生 select 使用不准确 label 定位；改为校验评测默认路由与 heading、精确 combobox 和四个 option，相关 12 项中的 landing 通过，最终评测专项 **7 项通过**，未放宽协议/密钥隔离断言。

布局程序检查：桌面 1440px 下评测首页/模型/组件/报告，以及移动 390px 评测首页无文档横向溢出；截图仅保存在忽略的运行目录。此项是浏览器几何检查，不代表已做人工视觉验收。
最终结果补充（2026-11-07）：普通 Playwright 浏览器回归 **158 项全部通过**（`CI=1 PLAYWRIGHT_SKIP_WEB_SERVER=1 ... playwright test --workers=1 --reporter=line`）；单独认证恢复用例 **2 项通过**。最终再次执行前端 `check` 与全量 `format` 均通过。验证副本曾将认证回归生成的 `test-results-auth/.last-run.json` 扫入 Prettier；仅将该临时输出移出源码目录后重跑，没有修改规则、放宽断言或更改产品代码。

本地 Docker 已更新为本轮构建的网关/前端，入口仍为 `http://127.0.0.1:2026`。网关与 Redis 健康，前端生产构建完成；HTTP 冒烟验证首页/登录页可达、未登录工作区重定向至登录、受保护的模型/报告/定时评测 API 返回 401。现有账号、凭据、配置和数据卷未重置；未代用户登录或创建账号，未执行真实模型或客户接口请求。镜像、运行配置、截图和结果仅保留于忽略的本地运行目录，不进入提交。

更新后真实本地入口另做 headless 浏览器冒烟：从 /workspace 自动跳转 /login，标题 DevPilot，邮箱输入可编辑并清空，无页面异常或 5xx。未提交登录表单、未创建账号，也未尝试绕过认证进入用户工作区。

## 2026-11-07：QA 数据最小闭环最终验证

本轮新增的是“本人项目 → 数据集草稿 → JSON/JSONL 导入 → Q/预期/来源并排复核 → revision/hash 冻结”的最小闭环。验证使用合成数据和 mock，不读取客户原始材料、历史报告、金标文件或真实组件接口；冻结是数据集所有者的自审确认，不等同于独立双人审批、来源授权核验或组件验收通过。

### 最终回归结果

- 后端离线完整套件：**11,404 passed、73 skipped、39 warnings**，330.34 秒；跳过不计通过。
- 后端专项：QA 数据、项目路由、持久化迁移、权限共 **51 passed**；纯领域 unittest（evaluation 15 + toolkit 58）共 **73 passed**。
- Ruff：`ruff check .` 通过；`ruff format --check .` 对 **1,161 个文件**通过；新增纯领域文件的 Ruff 与格式检查也通过。
- 前端：check（ESLint + TypeScript）、全量格式化、生产构建均通过；单元测试 **128 个文件 / 988 项通过**。
- Playwright：普通回归 **161 项通过**，独立认证恢复 **2 项通过**；新增数据页覆盖创建、导入、显式读取参考、确认冻结、503 错误、409 冲突撤销及移动端无横向溢出。无重试或放宽断言。
- 宿主与隔离测试副本的 **16 个后端 Python 文件、5 个前端 TS/TSX 文件**逐一 SHA-256 对比一致。

过程失败保留：较早完整后端出现 5 个旧权限期望失败，更新测试以覆盖新增的 3 个独立权限后重跑通过。安全复查先新增回归，复现 3 个失败：确认字段不应接受数字代替 JSON true，数据库异常不应回显含金标的 SQL 参数；修复后专项 51 项、完整 11,404 项通过。新页面浏览器测试最初的错误提示和原生下拉定位不准确，改为精确 alert 元素/combobox 定位后重跑；没有修改产品超时、跳过测试或降低安全断言。

### 本地 Docker 更新

本地入口仍为 `http://127.0.0.1:2026`。本轮运行镜像为 `devpilot-local/gateway:qa-data-20261107` 与 `devpilot-local/frontend:qa-data-20261107`；网关健康，未登录访问评测数据、模型、报告和定时评测接口均返回 401。升级前已在私有数据卷内完成 SQLite online backup，并确认原账号、Harness 迁移版本未改变，App 独立迁移账本为 `eval_0001`；运行配置、备份、截图和日志均未进入 Git。

### 未宣称的能力

真实 PostgreSQL 集成验收、数据生成 Agent、组件/提测版本关联、冻结数据驱动效果/性能执行、独立人工复核中心、CV 标注治理、跨集防泄漏、耐久任务队列、可运行脚本导出和证据报告仍未在本轮实现。下一优先级是把冻结数据集作为正式执行输入，并建立组件/提测版本、运行证据、结果复核和报告的持久关联。

本节数字仅代表本地隔离验证；新提交的 GitHub Actions 必须按新的 commit SHA 单独核对，不能用历史提交的绿灯替代。

## 2026-11-07：项目组件与不可变提测清单最终验证

本轮为 owner 项目的非可执行库存关联：已有组件 → 项目组件 → 同项目 frozen QA revision/hash → 多个不可变提测版本。新增 App 迁移 eval_0002，不改写已部署 eval_0001 或 Harness 账本；没有 RequestSpec 锁定、执行批准、真实接口调用、结果裁判或报告证据关联。所有测试仅用合成数据和 mock。详见[提测清单实现](DevPilot_项目组件与提测清单.md)。

### 本地回归

- 后端完整离线 pytest：**11,424 passed、73 skipped、39 warnings**，481.37 秒；跳过不计通过。
- 项目/QA/提测路由、仓储、迁移及权限专项：**71 passed**；纯领域 unittest：evaluation 15 + toolkit 58，共 **73 passed**。
- Ruff check 与 format --check 均通过，后端 **1,166 个文件**格式检查通过。
- 前端全仓库 format、ESLint/TypeScript、生产 build 通过；单测 **128 文件 / 988 项通过**。
- Playwright 普通完整回归 **163 passed**；独立认证恢复 **2 passed**；数据与提测专项 **5 passed**。新增测试覆盖关联、服务端 binding 入参、显式确认与撤销、不可变版本显示、503、页面无持久缓存、390px 无横向溢出。
- 宿主与隔离验证副本的 **8 个后端 Python、4 个前端 TS/TSX 文件** SHA-256 逐一一致。

过程问题不隐去：TDD 初始缺失 registry 模块出现预期红灯；新增 Unicode 版本名规范化后超长回归先失败，随后加 240 字符键界限，最终专项与全量通过。前端初次 lint 发现内部导航使用 a，改为 Next Link；新增 E2E 初次错误使用不存在的 Current project 标签，改为实际 Select project 精确 combobox 后通过。未加长超时、跳过用例或降低权限/秘密断言。

### 本地运行升级

已构建并运行 devpilot-local/gateway:submission-inventory-20261107 与 devpilot-local/frontend:submission-inventory-20261107。统一入口仍为 `http://127.0.0.1:2026`；先在私有数据卷中完成 SQLite online backup 并验证完整性，然后仅更新本项目 gateway/frontend，刷新 nginx。核对原账号保留、旧 QA 五张表逐行未改变、Harness 账本不变、新 App head 为 eval_0002、新增表就绪，外键检查通过。未删卷、重置账号或操作其他项目容器。

HTTP 冒烟：health/login 200；项目、候选组件、项目组件、提测快照、审计以及模型/报告/定时接口未登录均 401；工作区数据页跳转登录。没有代用户登录、创建账号或真实模型/客户请求；真实用户登录后的视觉验收仍需使用者确认。备份、运行配置、截图、辅助脚本和输出均留在忽略目录，不进入 Git。

### 未完成与远端边界

真实 PostgreSQL 集成、RequestSpec/凭据引用与调试确认的持久版本、清单导入模板、CV 样本、数据生成 Agent、耐久执行、结果复核和报告证据仍待开发。本轮测试通过不代表这些能力已完成，也不代表 GitHub Actions 通过。远端推送与新 commit 对应 Actions 状态以实际命令结果另行核对。


## 2026-11-07：导航修复与统一出站最终验证

本轮修复组件测试重复导航、未启用助手的死入口及移动切页抽屉；调试/手动/定时组件调用复用 App 出站传输，手动运行在创建记录前校验权限和目标策略，独立 toolkit 恢复 TLS 校验。完整请求版本、凭据引用、耐久队列、逐条观测/人工复核及报告证据仍未实现。详见[本轮范围](DevPilot_导航与统一出站基线.md)。

### 本地隔离回归

- 后端完整离线 pytest：**11,451 passed、73 skipped、39 warnings**，542.22 秒；跳过不计通过。
- 出站/组件执行/路由/调试/定时专项：**62 passed**。纯领域 unittest：evaluation **15 passed**、toolkit **58 passed**。
- 后端全量 Ruff check 和 format --check 通过，**1,167 个文件**格式检查通过。
- 前端 ESLint/TypeScript、修改文件格式化与生产 build 通过；单测 **128 文件 / 988 项通过**。
- Playwright 普通完整回归最终 **166 passed**；独立认证恢复 **2 passed**；导航/调试/评测工作台专项 **16 passed**，修正后的移动导航与主题专项 **10 passed**。专项为交叉覆盖，不重复累计成总量。
- 宿主与隔离副本的 **6 个后端/领域 Python 文件、9 个前端 TS/TSX 文件**逐项 SHA-256 核对一致。

过程问题保留：新增后端出站回归先出现 18 个失败；统一传输及准入后转绿。新导航回归先复现重复入口和置灰占位；移动测试进一步复现切页后抽屉未关闭，修复 WorkspaceSidebar 后通过。首轮完整浏览器回归为 164 passed / 2 failed：一处旧断言仍查找更名前的 Agents；另一处通过直接改 html 类切主题，与主题初始化竞争。已同步新名称并改用实际设置页主题按钮，保留明暗 ring 不同且非透明断言；最终完整 166 项通过。没有跳过失败测试、放宽断言或增加重试来获取绿灯。

全部使用合成数据和 mock；脱敏扫描仅命中安全拒绝测试中显式写出的合成私网地址，已人工确认，不是客户地址。不上传原材料、业务场景名称、历史业务指标、凭据、运行配置、数据库、备份或本地测试日志。

### 本地部署的真实状态

已构建 devpilot-local/gateway:outbound-nav-20261107 与 devpilot-local/frontend:outbound-nav-20261107，升级前 SQLite online backup 在私有卷内完成并通过完整性检查。服务切换的执行审批连续两次超时，因此本轮**尚未激活新镜像**；compose 仍选择 submission-inventory-20261107，现有入口仍为上一轮界面。未重置账号、删除卷或改动其他项目容器。

完成服务切换后仍须验证网关/前端健康、未登录接口保护、原账号/评测数据及两套迁移账本一致性；没有以隔离回归冒充本地新版运行验收。配置中尚无真实模型，真实模型和客户接口验收未执行。

本节仅记录本地验证。Git 提交/远端推送和对应 commit 的 Actions 状态以实际结果另行核对，不据此宣称 GitHub Actions 已通过。
