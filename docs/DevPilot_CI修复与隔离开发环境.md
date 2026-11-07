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
