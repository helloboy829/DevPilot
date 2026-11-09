# CI 修复与隔离开发环境

> 2026-11-07。仅记录本轮已执行的工程验证；不等于生产部署验收、真实组件效果验收或安全整改全部完成。不会改 Conda base，也不操作现有业务容器。

## 1. 真实失败原因

核查 GitHub 仓库 helloboy829/DevPilot 两次提交的实际 job 日志，而不是根据邮件猜测：b7f930a4669713125c116350af331679d7577bfa、5c43303d383097fb4fa3cbd74905d4d002d0aa34。

| Workflow            | 失败点                                                                                   | 修复方式                                                                                                                                     |
| ------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit Tests          | 1 项文档清理回归仍读取 3 份已移除的历史文档；9 项迁移/并发回归写死旧 head 0011_mcp_tasks | 改为校验当前维护的入口/架构/部署文档；历史 seed 仍保持原迁移，最终 head 使用实际迁移链；中央测试保留明确 head pin，新增迁移幂等/旧库升级回归 |
| Frontend Unit Tests | 文档 layout 文件缺失，样式隔离回归无法读取                                               | 恢复英文/中文 docs layout 与 MDX catch-all 路由，增加 page-map 和语言/路径边界测试                                                           |
| E2E Tests           | 文档页面 404，4 个卡片/Markdown/反馈编辑链接用例失败                                     | 恢复路由与本地化 page map；编辑和反馈指向当前 fork；保留原测试，新增不支持路径 404 回归                                                      |
| Lint Check          | 4 个前端文件不符合 Prettier 格式，后续检查尚未执行                                       | 按锁定依赖格式化；继续执行 ESLint、TypeScript、生产构建，不以关闭检查修复                                                                    |

本地完整基线还暴露一个离线单测依赖真实 DNS：Crawl4AI HTTP client 已 mock，但 URL 安全检查仍解析 example.com。在测试中 mock 公网 DNS 地址，并新增无法解析主机的拒绝回归；保留私网/元数据地址拒绝测试，生产 URL 安全逻辑不改。

两个原提交均有相同 CI 失败；此次修复尚须新提交的远端运行确认，不能用本地通过替代 Actions 结果。

## 2. 本轮使用的隔离环境

| 用途     | 环境                                                                                                |
| -------- | --------------------------------------------------------------------------------------------------- |
| 后端     | python:3.12-bookworm，实际 Python 3.12.16，uv 0.13.7；uv.lock 冻结安装 dev + postgres；Ruff 0.15.12 |
| 前端     | node:22-bookworm，实际 Node 22.23.4、pnpm 10.26.2；frozen-lockfile；Playwright Chromium             |
| 集成服务 | postgres:17、redis:7-alpine，专用 devpilot-ci 网络，不发布宿主端口                                  |
| 代码     | 受控源码快照复制到容器 /workspace；不是宿主目录挂载，不带密钥/运行配置/客户原件                     |

容器名 devpilot-ci-python、devpilot-ci-node、devpilot-ci-postgres、devpilot-ci-redis。无 Docker socket 挂载、无宿主端口发布；不与既有业务服务共享数据卷。测试镜像/依赖下载需要网络，测试不调用用户材料中的目标接口。完整后端部分集成用例仅访问隔离测试服务。

镜像 digest（本轮实际拉取，仅用于复现，不承诺将来标签不变）：

- Python: sha256:4209fae09a3e20afd863e528bfddc235da5fd5977983e1996cd54cc9a72e6267
- Node: sha256:7702d8aa4d5910871692af4480eb3ba86f23047a6417a44d857d06c95d060d3f
- PostgreSQL: sha256:748a18a54d3842d43bc156f0840d78029b8d349e0feca98c12b9c4ce3404a6b3
- Redis: sha256:c5d34a98396a4775e223c74e929162c35c5a2182901ba26b50ade939941ce14b

Conda 可用于另建指定 Python 版本的环境，但不与 Docker 环境叠加作为必需步骤；本轮以更接近 CI 的 Linux Docker 环境为准，未修改宿主 base。该环境不是项目的生产镜像。

## 3. 可复现操作

以下是手动复现步骤，不是自动创建脚本。仅在容器名未占用时创建，重复执行前先检查已有资源；不要删除其他容器或执行全局 prune。PowerShell 在仓库根目录执行：

```powershell
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
```

测试服务（以下密码只是一次性隔离测试值，不能用于部署）：

```powershell
docker network create devpilot-ci
docker network connect devpilot-ci devpilot-ci-python
docker run -d --name devpilot-ci-postgres --network devpilot-ci -e POSTGRES_USER=deerflow -e POSTGRES_PASSWORD=ci-local-only -e POSTGRES_DB=deerflow_test postgres:17
docker run -d --name devpilot-ci-redis --network devpilot-ci redis:7-alpine
docker exec devpilot-ci-postgres pg_isready -U deerflow -d deerflow_test
docker exec devpilot-ci-redis redis-cli ping
```

确认服务 ready 后：

```powershell
docker exec devpilot-ci-python sh -lc 'cd /workspace/backend && make lint && TEST_POSTGRES_URI=postgresql://deerflow:ci-local-only@devpilot-ci-postgres:5432/deerflow_test?sslmode=disable DEDUPE_TEST_POSTGRES_URL=postgresql://deerflow:ci-local-only@devpilot-ci-postgres:5432/deerflow_test?sslmode=disable DEER_FLOW_TEST_REDIS_URL=redis://devpilot-ci-redis:6379/15 make test'
docker exec devpilot-ci-node sh -lc 'cd /workspace/frontend && python3 /workspace/scripts/pnpm.py format && python3 /workspace/scripts/pnpm.py check && python3 /workspace/scripts/pnpm.py test && BETTER_AUTH_SECRET=local-dev-secret python3 /workspace/scripts/pnpm.py build'
docker exec devpilot-ci-node sh -lc 'cd /workspace/frontend && CI=1 SKIP_ENV_VALIDATION=1 python3 /workspace/scripts/pnpm.py exec playwright test --reporter=line && CI=1 SKIP_ENV_VALIDATION=1 python3 /workspace/scripts/pnpm.py exec playwright test -c playwright.auth.config.ts --reporter=line'
```

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

本轮为 owner 项目的非可执行库存关联：已有组件 → 项目组件 → 同项目 frozen QA revision/hash → 多个不可变提测版本。新增 App 迁移 eval*0002，不改写已部署 eval_0001 或 Harness 账本；没有 RequestSpec 锁定、执行批准、真实接口调用、结果裁判或报告证据关联。所有测试仅用合成数据和 mock。详见[提测清单实现](DevPilot*项目组件与提测清单.md)。

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

## 2026-11-09：当前状态校准、Docker 全量回归与 PostgreSQL TLS 兼容

本轮源码起点为 `d2a58a390971d15e4b84f08a79f484bf0e86dc52`；工作区另有状态文档和 PostgreSQL URL 修复。最近独立验证的运行部署仍为 `0fd689da83a4ac7646250447fb6d044599a823c5`、App head `eval_0009`，本轮没有构建/切换生产镜像或改变配置。历史 Actions 成功不代表当前 HEAD/工作区 CI 已通过；本轮没有远端核验。当前能力/未完成门禁统一见[交付矩阵](DevPilot_Delivery_Status.md)。

### 环境与基线

复用既有 `devpilot-ci-python`（Python 3.12.16）、`devpilot-ci-node`（Node 22.23.4）与专用 PostgreSQL 17/Redis 7 容器，不使用宿主旧版本完成正式回归。从 `git archive HEAD` 导出受跟踪源码，仅叠加显式改动；不复制私有配置、账号库或客户材料。后端导入路径指向新快照；锁文件与已有依赖缓存一致，无依赖升级。

前端初次把 `node_modules` 符号链接到快照外，Turbopack 正确拒绝越界；改为同文件系统硬链接依赖树后生产构建通过，没有放宽构建边界或下载第二份依赖。独立 PostgreSQL schema 检查使用本次 CREATE 成功的临时库，`finally` 删除；共享测试库不冒充空白 public schema。Node 健康探针补测复用已有 Node 二进制。

| 验证组                                         | 本轮实测结果                                                          | 边界                                                            |
| ---------------------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------- |
| 修复前后端完整离线基线                         | 12,038 passed / 69 skipped / 11 deselected / 40 warnings，463.86s     | 未启用专用 PG/Redis 环境；跳过不算通过                          |
| 修复前后端完整集成基线                         | 12,082 passed / 25 skipped / 11 deselected / 40 warnings，496.57s     | 专用 PG/Redis；schema 与 Node 探针另补                          |
| 修复后后端完整集成回归                         | **12,118 passed / 18 skipped / 11 deselected / 40 warnings，434.04s** | PG/Redis 与 Node 可用；独立 schema 两项在专用库补测，不合并计数 |
| 修复后纯领域 unittest                          | evaluation **15** / toolkit **58** 通过                               | 按各自套件记录，不与 pytest 数量拼接                            |
| 修复后 Ruff check / format                     | 通过，**1,220 文件**格式检查通过                                      | 包含新增回归文件                                                |
| PostgreSQL 新回归红阶段                        | 25 failed / 4 passed                                                  | 稳定复现参数传递、歧义拒绝问题，不删除安全断言                  |
| 修复后相关定向回归                             | 120 passed                                                            | 包含新增 29 项及既有持久化/配置/schema 单测；与完整套件重叠     |
| 独立 schema + Node 健康探针补测                | 修复前 25 passed / 1 failed；修复后 26 passed                         | 临时专用测试库已移除；没有真实目标/模型调用                     |
| 前端全仓库 format、ESLint/TypeScript、生产构建 | 通过                                                                  | 不以 lint/typecheck 代替 format 或生产构建                      |
| 前端单测                                       | 140 文件 / 1,094 项通过                                               | 与浏览器测试分开记录                                            |
| Playwright 常规完整回归                        | 201 passed，单 worker、零重试                                         | 不以浏览器 fixture 证明生产执行或客户效果                       |
| 独立认证恢复回归                               | 2 passed，单 worker、零重试                                           | 与普通套件分开记录                                              |

### 修复的真实问题与排除范围

额外 schema 集成测试发现：libpq DSN 的 `sslmode=disable` 原样传入 SQLAlchemy asyncpg 关键字参数，触发 `TypeError: connect() got an unexpected keyword argument 'sslmode'`。这不是数据库不可用，不通过去掉 TLS 参数、跳过测试或改变同步路径来掩盖。

仅 `DatabaseConfig.app_sqlalchemy_url` 在派生 asyncpg URL 中将单一有效 `sslmode` 改名为 `ssl`，保留六种模式的原值、编码凭据及其他 query 值；原 DSN 与同步 psycopg URL 不变。重复、空/未知模式及与 `ssl` 同时指定均用通用错误拒绝，不回显 URI/凭据、不默认降级。新增 `backend/tests/test_postgres_url_sslmode.py` 先红后绿。

没有新增依赖、迁移、生产配置/密钥、目标/模型调用，也没有升级生产。该补测不是证书链/远端 TLS 部署验收。真实模型和显式 Docker 生命周期测试仍受独立开关约束；没有偷偷开启 live gate。

### 源码与证据

本地 ignored 目录 `.deer-flow/verification/20261109/` 保存测试收据和更新后的 runtime manifest。修复后的 626 个后端 Python 运行源码规范 CRLF→LF 后一致，其中 27 个仅原始换行不同；528 个前端源码原始 SHA-256 全部一致。不能把后端规范化一致写成原始字节完全一致，也不能把有重叠的定向/补测与全量简单相加。

新文档链接已按本轮范围核对；backend 指南仍有继承的历史断链/示例引用，不宣称全仓历史文档链接全部通过。Docker 精确退役与最后健康/测试资源收尾另见[运维记录](DevPilot_Docker_Diagnostics.md)。

最终文档相关契约另测 22 passed（与完整套件重叠）；前端指南变更后再次整个 frontend format 通过。收据已保存到 ignored 验证目录；临时测试快照/Node/源码 tar 已清理，四个本次启动的 CI 容器已停止，共享依赖缓存保留。最终业务健康检查通过；精确资源记录见运维文档。本轮没有提交、推送或部署；整个项目与用户最终验收仍未完成。

## 2026-11-09：API → 实际 Worker 合成闭环回归

本轮仅新增 `backend/tests/test_qa_workflow_api.py`，没有新增运行功能、依赖、迁移或生产配置；前述 TLS 修复仍为既有未部署的工作区变更。使用 HTTP 创建三样本冻结 QA、两个完整请求版本、v2 阈值计划和独立执行准入，再运行实际 `QAExecutionWorker`、采集器、持久派发/加密证据、人工决策、汇总、报告/Word 和复测档案。并发 1/2、六类输出/网络失败共 **8 项通过**；不是浏览器、真实认证、部署或客户目标验收。

- 替身只位于 DNS/HTTP wire；认证、数据和 key 明确是临时合成配置。禁用真实 socket 解析/发送，核验 IP pinning、Host/SNI、TLS/无重试参数和输入不带金标。生产执行策略没有开启，未调用真实模型或目标。
- 发送前从另一数据库会话验证派发已提交、配额仍持有；两版请求都先冻结，再执行旧版，防止偷用最新版本。准入和重复的已知成功 receipt 不能增加发送，未知交付中断且不重发。
- 2/3 在 6667 bps 下未达标，3/3 达标；错误、未发出和不确定仍留在全量分母，零阈值也不放行；完整或 `met` 始终不是批准。
- 后续人工修订改变当前汇总，不改写历史报告/Word/复测；过时 hash、新归属或 Agent/匿名读取拒绝。去掉临时 key 或禁用当前模板后历史下载仍基于冻结档案，不渲染新模板。

### 环境失败与修复证据

初次快照全量在收集期出现 **44 collection errors / 5 skipped / 11 deselected**：缺少 `devpilot/src` 导入路径及静态检测使用的仓库根标识。仅修正隔离环境后，第二次全量为 **13 failed / 12,104 passed / 19 skipped / 11 deselected / 40 warnings**，失败集中于清空父进程 PYTHONPATH 的子进程策略测试；可编辑安装路径尚不可靠。未据此修改业务代码、减少断言或跳过失败。

检查时共享 venv 的三个 editable `.pth` 已指向本轮快照，但未记录最初内容，不能断言具体是哪一步改写。随后为快照建立独立 venv 目录（硬链接复制依赖，先断开 `.pth` 链接再写入），共享缓存恢复到稳定 `/workspace` 源码；核验两套解释器的 `sys.prefix` 和无 PYTHONPATH 导入。设置 `UV_NO_SYNC=1`，避免常规 `uv run` 同步共享安装。子进程策略定向 **18 passed** 后，完整变更前基线 **12,117 passed / 19 skipped / 11 deselected / 40 warnings，416.45s**；2,446 个源码文件哈希一致，新增回归尚未进入该基线。

### 本轮门禁与证据范围

- 新增链路 **8 passed**（11.06s）；完整变更后 **12,125 passed / 19 skipped / 11 deselected / 40 warnings，430.43s**。
- 两个纯领域套件分别 **15 / 58 passed**；完整 Ruff check 与 format 通过，**1,221 文件**。定向测试与全量重叠，不相加。
- 本轮没有修改前端源码，之前的前端构建/1,094 单测/201+2 浏览器结果保留为前一轮证据，未冒称重新执行。上轮 PostgreSQL schema 独立补测不拼接进本次完整计数，跳过不算通过。
- ignored `.deer-flow/verification/20261109/evidence/qa-chain/` 留存源码 manifest、初次失败/后续回归、环境恢复与清理收据。没有提交、推送或部署；当前运行 SHA 和 `eval_0009` 不变。

最终文档同步后 Docker 默认绑定、前端运行命令、pnpm 启动器、只读诊断与健康探针契约 **91 passed**（2.92s）；与完整套件重叠，不相加。运行代码和已通过全量的新增测试未再修改。

02:06 资源收尾完成：本轮三个 CI 容器停止、Node 保持停止；独占临时快照/venv/Node/源码 tar 删除，共享 editable 缓存稳定路径与哈希保留。2,447 个源码文件同步核验无差异，随后只追加最终运维文字。其他容器/当前镜像未变，业务四服务 healthy、只读诊断 ok；日志和清理收据保留。最终健康诊断按实际支持的 `--project` 参数运行，JSON 由外层保存（脚本不提供 `--output` 参数）。

## 2026-11-09：独立逐条复核后端/API 候选验证

本轮复用同一组停止状态的 CI 容器后，仅启动 Python 3.12、PostgreSQL 17、Redis 7；Node CI 未启动，Node 二进制及本地已有 Prettier 仅复制到本轮临时目录。只导出 Git 源码及显式列出的新增文件，不复制生产配置/数据；专用数据库、合成用户/key/材料，不启用真实模型/目标。当前运行仍为 `0fd689da83a4` / `eval_0009`，候选后端新增 `eval_0010`，没有提交、推送或部署。

### 基线失败与不确定性保留

- 初次 37 collection errors 发生于隔离 venv 的命令启动脚本仍指向共享 `/workspace/backend/.venv`。断开快照中的硬链接后重写 51 个 launcher，并核验共享文件与三个 editable `.pth` 原哈希，未用业务修改修补环境。
- 首次正确隔离全量为 **1 failed / 12,124 passed / 19 skipped / 11 deselected / 40 warnings，442.58s**。`test_parallel_render_completion_cannot_reorder_durable_dispatch` 在 Worker `finish` 时得到 `JournalWriteUnconfirmed`，**根因未确认**；没有增加自动重试、放松派发断言或跳过该用例。该整个文件随后 **25 passed**，完整变更前复验 **12,125 passed / 19 skipped / 11 deselected / 40 warnings，429.47s**。失败仍是需要追踪的稳定性信号，后来的通过不抹除它。
- 新服务红测试、首次迁移 task_id 缺显式类型、合成观测枚举/HTTP status fixture 的开发失败日志均保留。修复新迁移为显式 `String(32)`，fixture 遵循既有 `policy_rejected` 无 HTTP status 的契约；没有削弱运行时校验。一次写错旧测试节点名未执行任何用例，正确节点随后单独运行。

### 新切片定向与隔离边界

后端服务/API/迁移加现有 SQLite schema 对照 **67 passed，36.40s**。覆盖两个独立盲审与第三人仲裁、无项目成员授权、租约/回执/CAS、并发/撤销、SQL/响应隐私、密文/结论篡改、未知提交同 ID 核对及原子审计回滚；历史 SQLite 所有旧表数据、Harness ledger 不变。PostgreSQL 测试在自己创建的 UUID 数据库内执行迁移/metadata 对照/降级回升，最终仅删除该精确临时库，不迁移共享传入库。

没有新增复核 UI、assessment/报告接入或正式批准；[合同与排除范围](DevPilot_Independent_Case_Review.md)与当前矩阵同步。前端源码未变，本轮不把历史前端全量/浏览器通过说成重跑。源码 manifest、环境收据及各次日志独立留存在 ignored `.deer-flow/verification/20261109/evidence/independent-review/`，保留完整失败史而不是只保存最后一次通过。

变更后第一次完整回归为 **1 failed / 12,190 passed / 19 skipped / 11 deselected / 40 warnings，461.98s**：旧 `eval_0008` 保留测试从当前 metadata 枚举了当时不存在的新 task 表。仅修正测试为检查旧库实际存在的全部 `evaluation_*` 表，并断言全部在 metadata 中、报告表存在而复测表尚不存在；逐表前后内容比较与 Harness ledger 断言保留。相关复测及新迁移文件 **24 passed，11.47s**；随后重新执行完整套件，没有把第一次失败当通过或跳过。

最终完整变更后复验 **12,191 passed / 19 skipped / 11 deselected / 40 warnings，471.47s**；纯领域 evaluation/toolkit 分别 **15 / 58 passed**。Ruff 全量 check/format **1,227 文件**通过。定向 67、迁移关联复验 24 与完整套件有重叠，不相加；skipped/deselected 不算通过。 首次基线派发收尾的未定位失败继续留档，不因最后通过就声称根因已解决。

最终 Docker/文档相关契约 **91 passed，2.91s**（与全量重叠）；十二份本轮 Markdown 使用已缓存 Node/Prettier 检查通过，不代表前端其他门禁重跑。运行/测试代码在完整回归后未再修改。28 份日志/环境收据已留存并逐项哈希验证；临时快照和辅助文件精确清理，共享 editable/51 launcher 哈希及稳定导入核验通过。本轮三个 CI 容器已停止，Node 保持停止；全部其他容器/镜像不变，四业务服务 healthy、只读诊断 ok。没有新增镜像删除或部署，资源收据见维护记录。最终收尾文字属于全量测试后的文档追加，不冒称完整套件又重跑。

## 2026-11-09：共享独立复核 UI 候选验证

只启动既有 Node CI（22.23.4 / pnpm 10.26.2），Python/PostgreSQL/Redis CI 均保持停止。源码快照不含私有环境文件、业务数据库、key 或客户材料，已有 node_modules 只复用，无依赖安装/新镜像/业务替换。生产构建与容器回环测试服务分开运行，服务启动不编译；执行始终经 `scripts/pnpm.py`。

### 前端候选验证（2026-11-09）

- Docker Node 22.23.4 / pnpm 10.26.2 隔离快照，复用已有依赖与 Chromium，无依赖安装或新镜像。全量前端单测 **144 文件 / 1,125 passed**（17.9s），其中本切片四文件 **31 项**，不与全量相加；lint/typecheck、生产构建已通过。最终再次执行完整 frontend Prettier（含前端指南）、lint/typecheck 和全量单测：均通过，单测仍为 **144 文件 / 1,125 passed，18.1s**；不是新增 1,125 个测试，不与前次重复计数。
- Chromium 模拟 API 的完整工作区浏览器 **206 passed**（3.9m，含本切片 5 项），独立登录/设置恢复 **2 passed**（1.6s）；均 `--retries=0`。覆盖 1440/390px、键盘、逐次明确同意、字面文本/无外链加载、双盲/仲裁、unknown create 跨项目 GET 核对和不可变历史轮次。
- 初次定向 23 passed / 4 failed（测试 hook 与假计时器错误）已修正；第一次全量快照漏带两个公开 contracts 文件导致两个测试文件收集失败，补齐隔离快照后全量重跑。首轮浏览器 **3 passed / 1 failed** 发现移动端长按钮溢出，修复换行/fieldset 最小宽度后五项定向及全量通过，保留原失败上下文，没有隐藏溢出或删除断言。补充租约过期后的迟到响应回归，防止重新展示敏感内容。
- 不支持的 Rstest `--run` / Playwright screenshot CLI 参数失败留存，后续用受支持命令重跑；不把未执行命令算测试结果。最终类型导入告警已修正。
- 没有本轮后端测试重跑、真实认证多账号互通、连接实际后端的 UI 验收、真实模型/目标效果验收、远端 CI、提交/推送、生产迁移或部署。先前后端 12,191 项属于独立历史切片；最终用户验收和正式批准仍未完成。

本地证据目录：ignored `.deer-flow/verification/20261109/evidence/review-ui/`，保留早期红测试、工具参数失败、移动端失败上下文及后续通过结果。共享缓存收尾仅核对明确的文件标识，不把少数哈希扩张为整个依赖树审计。最终源码同步、格式与资源结果另追加。

### 最终源码与资源收尾（2026-11-09）

最终完整 frontend Prettier（含前端指南）、lint/typecheck 与全量单测均通过，单测为 **144 文件 / 1,125 passed，18.1s**；另外十三份本轮源文件/指南的 Prettier 检查通过。833 份快照文件与最终宿主清单逐项 SHA-256 一致；37 份日志/收据导出后再次逐项校验，保留失败及通过结果。

独占 Docker 快照、辅助文件、证据临时副本和宿主 staging 已按精确路径清理；五个共享 Node 缓存标识哈希未变，Chromium/可复用依赖保留。仅停止本轮 Node CI，其余三个 CI 保持停止；全部其他 13 容器与镜像清单未变，无可安全删除的过期 DevPilot 镜像。最后业务四服务 healthy、restart=0、OOM=false，诊断 ok。详情与证据边界见[资源维护记录](DevPilot_Docker_Diagnostics.md)。

本节与资源收尾文字属于通过测试之后的纯文档追加；不是又一轮完整测试、远端 CI 或部署。候选仍未提交/推送/部署，真实多账号 UI/后端联调、正式审批与最终用户验收仍未完成。

## 2026-11-09：全样本独立评估与不可变修订候选验证

候选 App head 为 `eval_0011`；只在既有 Python 3.12 CI 的独占源码快照中运行，复用专用 PostgreSQL/Redis 和共享依赖。测试使用合成数据/key，不复制部署库、私有配置或客户材料，不开启真实模型/目标调用。Node CI 始终停止；本轮没有前端源码改动或前端全量重跑，前轮证据不能算作本轮结果。

- 变更前完整基线 **12,191 passed / 19 skipped / 11 deselected / 40 warnings，498.40s**；最终完整候选 **12,231 passed / 19 skipped / 11 deselected / 40 warnings，489.52s**。新增 40 项，跳过/排除不算通过；修正后定向 **104 passed，48.14s** 与完整套件重叠，不相加。后续增加的预览/归档竞争和提交前/后 unknown-write 变体已被最终完整套件覆盖。
- 纯领域 evaluation/toolkit 分别 **15 / 58 passed**。全 backend Ruff check 通过，format --check **1,232 文件**通过。七份初次同步 Markdown 的 Prettier 检查通过；最终文档追加另做格式核对，不据此声称运行代码又重跑。
- 仅复制新测试到旧快照，先观测到缺失 `app.evaluation.qa_assessments` 的红灯。第一轮定向 **1 failed / 90 passed**：迁移 parity 错把 Harness 的既有 `component_tests` 当成多余 App 表；修正为联合真实 metadata，仍检查旧行保留。
- 扩充定向 **6 failed / 98 passed**：缺派发测试被真实 FK 拦截，改用明确缺失的 snapshot 注入测试分析器而不禁用 FK；四个证据 fixture 使用错误，改用真实 captured 输出；PostgreSQL datetime 的测试基线不应使用 SQLite 表示，改为同 PostgreSQL 迁移前/后整行比较，未忽略字段或削弱数据保留检查。随后 104 项及最终完整套件通过，保留所有失败记录。
- 完整回归后，导出的 **2,472 份公开源码 SHA-256** 全部与测试快照一致；之后仅同步 Markdown 和 ignored 收尾证据脚本，不改运行/测试源码。历史 Worker `JournalWriteUnconfirmed` 偶发基线失败的根因仍未确认，不因本轮通过而宣称解决。

19 份本轮测试/环境日志与 JSON 收据先导出并逐项验 SHA-256，清理回执另存；通过与失败都保留于 ignored `.deer-flow/verification/20261109/evidence/assessment/`。仅本轮独占快照/辅助文件和已验真的 Docker 证据副本被清理，三份共享 editable marker 与 51 个 launcher 在清理前后哈希一致，稳定路径导入通过；不是整个缓存树审计。专用 CI PostgreSQL 中 assessment 临时库数为 0。

三个本轮启动的 CI 已停止，Node 未启动；全 14 容器测试前/后 ID、镜像、运行/停止、restart/OOM 签名相同，镜像清单未变，四业务服务 healthy、诊断 ok。停止命令返回成功，但收尾脚本的 stdout 精确集合断言失败；未重做删除/停止，独立只读 inspect 完成最终确认。Python CI 最后 exit=137、OOM=false，不声称优雅退出。详见[维护记录](DevPilot_Docker_Diagnostics.md)。

未提交、推送、核验本候选远端 CI、部署或迁移生产。部署仍为 `eval_0009`；评估 UI、报告/复测显式绑定、正式批准及真实多账号/用户验收仍未完成。

### 独立评估 UI 候选的隔离验证（2026-11-09）

本轮新增两个单测文件（严格 DTO 19 项、DOM 8 项）及 4 项桌面/390px 模拟浏览器用例。完整前端 **1,152 passed / 146 文件**（最终 26.3s），完整模拟浏览器 **210 passed**（248.2s）、独立登录/设置恢复 **2 passed**（1.6s），浏览器均 `--retries=0`。定向 27 / 4 项包含在对应全量，不相加。整个 frontend Prettier（含指南）、ESLint/TypeScript 与生产构建通过；本轮没有重跑后端 12,231 项，不挪用前轮结果当新证据。

首次仅同步测试到旧快照，两文件因缺新模块变红；实现同步后，一项 fieldset 继承 disabled 的测试读取方式错误、DOM 查询类型选项及导入顺序暴露并修正，保留原失败日志。首次构建因跨快照 node_modules symlink 被 Turbopack 拒绝；改用同盘硬链接的独占依赖树，未放宽构建根、下载依赖或修改共享缓存标识；修正后生产构建和完整门禁通过。旧 Worker 偶发派发失败的根因仍未确认，本轮未声称解决。

这是公开源码快照、既有 Docker Node 依赖、合成 API 和容器 loopback 站点的验证，不是实际后端/多账号联调、远端 CI、正式批准或用户验收。没有生产迁移、key 生成、执行开关、真实模型/目标调用、提交、推送或部署。候选 head `eval_0011`、最近独立核验的部署 head `eval_0009`；独立报告/复测显式绑定、正式批准与保留数据部署仍待交付。

证据根目录：ignored `.deer-flow/verification/20261109/evidence/assessment-ui/`；包括基线、失败与通过日志、源码清单及资源收尾收据。两个测试站点在浏览器完成后已按进程组精确停止；最终格式、证据导出与精确临时资源清理后，仅停止本轮 Node CI。共享依赖与 Chromium 缓存不按“旧”自动删除。

本 UI 轮资源收尾已独立核验：30 份 Docker 日志/JSON 先导出并逐项验 SHA-256，834 份公开源码/测试/指南与测试快照一致；随后仅删除本轮独占快照、12 个辅助文件及已备份证据副本，宿主 staging 亦精确删除。仅停止本轮 Node CI，其余三个 CI 始终停止；最终全部 14 容器的 ID/镜像/运行或停止/restart/OOM 签名恢复测试前状态、9 行镜像标签清单不变。无可安全删除的无引用 DevPilot 镜像，本轮镜像/容器/卷零删除；业务四服务 healthy，诊断 ok。五个明确 Node 缓存标识哈希未变，不声称整个缓存树已审计。资源收尾后的追加仅为文档，不代表重跑完整套件或已部署。

## 2026-11-09：独立历史修订绑定报告/复测后端候选

候选 `eval_0012` 追加独立报告/复测表及 API，旧 owner 档案/模板/hash 不切换。复用既有 Python 3.12 CI、专用 PostgreSQL/Redis、共享依赖的独占硬链接快照；三份 editable 与 51 个 launcher 均先 unlink 再修改快照，保护原共享依赖。没有依赖安装、镜像构建、私有配置/业务库复制、生产 key 生成或真实模型/目标请求。Node CI 始终停止。

- 修改后完整后端 **12,284 passed / 26 skipped / 11 deselected / 40 warnings，593.12s**（wrapper 602.68s），exit=0。早前 **12,224 passed / 37 skipped / 40 warnings** 是变更前快照结果，不算本候选通过；未运行项不计为通过。
- 最终定向 **104 passed，86.21s**；新服务/七端点、历史完整修订、全量分母、类型/篡改、并发幂等/排序锁/最终重查/原子审计及 SQLite/独占 PostgreSQL migration parity/旧数据保全、旧 owner 路径通过。与全量重叠，不相加。两组纯领域 **15 / 58** 分别通过；Ruff check 与 format **1,237 文件**通过。
- 初期表导入 SyntaxError、错误假设 dispatch run 含 owner 字段、路由未实现、PostgreSQL 重复约束索引/审计快照、component 严格类型/criteria bool 类型和请求 hash 未 off-loop、Ruff 错误均原样留存；修正后重新执行定向和完整门禁，没有跳过失败或放宽隐私/保全断言。
- 运行/测试源码与真实测试快照逐项 SHA-256 相同；后补文档单独同步并格式检查。整个 frontend Prettier 与本轮 root/backend/文档指南通过；没有前端运行源码改动或前端单测/浏览器/生产构建重跑。

这是未提交工作区的离线候选验证，不是远端 CI、正式批准、真实多账号联调、生产迁移或保留数据升级；部署仍为 `eval_0009`。独立报告/复测选择 UI 与独立 Word/PDF、正式批准、用户验收仍未完成。历史 Worker 偶发派发失败根因未确认，不因本轮通过宣称已解决。证据保存于 ignored `.deer-flow/verification/20261109/evidence/independent-archives-v2/`；先导出和验 hash，后精确清理独占临时资源，再停止本轮启动的三个 CI，实际收尾另见运维记录。

本轮资源已独立收尾（2026-11-09 07:45）：19 份结果逐项导出验 hash；2,484 份最终公开文件与快照一致，初始 2,480 文件清单保留。独占快照/四个辅助文件/已备份副本/宿主 staging 精确删除，3 份共享 editable 和 51 个 launcher 哈希清理前后相同。三个本轮 CI 已停止、Node 始终停止，14 容器的明确签名恢复测试前状态，9 行镜像标签不变；业务四服务 healthy、只读诊断 ok，镜像/容器/卷零删除。Python stop 最后 exit=137、OOM=false，不声称优雅退出；没有活动测试被停止。收尾检查的 PowerShell 引号/沙箱日志写入失败单独留存，独立脚本在获准权限下完成后续检查。最后追加仅为文档/ignored 证据并单独格式检查，不算完整后端/前端重跑或部署。
