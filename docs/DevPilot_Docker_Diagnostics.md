# DevPilot Docker 只读诊断 / Read-only diagnostics

日期：2026-11-08。状态：新增运维脚本，不是 Docker 根因已经修复的声明，不自动更新部署。

## 目的

先区分 Docker 管理面无响应、应用容器异常、观测缺口和资源风险，再决定恢复动作。不能把“重启后恢复”当作长期修复，也不应在评测执行时自动重启、重试未知请求或删除数据。

生产前端已将构建与启动分离：重启只运行预编译 Node 服务，不重新 `build && start`。该改进减少重复启动开销，不足以证明 Desktop 卡顿的根因。详细恢复和保留数据升级见 [原恢复记录](DevPilot_Local_Recovery_and_Upgrade.md)。

## 使用

只依赖 Python 标准库与已安装的 Docker CLI，不依赖可用的后端环境。

```bash
python scripts/docker_health.py --project devpilot-local --timeout 5
# 等价 Make 入口；替换为实际 Compose 项目名
make docker-health DOCKER_HEALTH_PROJECT=devpilot-local
```

- 使用 Docker CLI 当前 context；脚本不会切换 context、启动 Desktop 或猜测其他项目。
- 项目名仅接受 1–64 位小写字母/数字/下划线/短横线，首位必须是字母或数字。
- 默认诊断本地 `devpilot-local`；其他部署必须传入实际 Compose project，不能将“选错项目后服务缺失”误判为数据丢失。
- 最多三次 CLI：格式化的 `docker info`、按 project label 过滤的 `docker ps`、最多 32 个容器的格式化 `docker container inspect`。每次默认 5 秒、共享最多三个超时窗口的截止时间；不重试。超时终止并回收 CLI 子进程，不停止 Docker 引擎或应用。
- CLI 输出仅读取至 64 KiB 并严格校验 UTF-8/JSON/类型/枚举；超界或畸形结果失败关闭，不回显原输出/异常。
- 只返回 gateway/frontend/nginx/redis 的固定字段。该项目中的其他服务不出现在报告；不枚举其他项目。

## 字段与判读

输出为 `schema_version=1` JSON；**不应只依据进程退出码判断全绿**。

| 字段       | 含义与边界                                                                                                                                   |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `status`   | `ok`、`warn`、`fail`。warn 的退出码仍为 0；fail 为 1。参数无效由 CLI 返回 2。                                                                |
| `docker`   | 仅 Docker 是否响应及可用 CPU/总内存数；错误为固定 reason code，不包含 stderr/上下文路径。                                                    |
| `services` | 固定服务的匿名实例数组，仅 state/health/restart_count/oom_killed/exit_code。尚未可靠查询为 null；可靠查得无实例才为 []。                     |
| `storage`  | 工作区卷与系统卷的容量/剩余字节，不输出路径。不知道就是 unknown，绝不伪造为 0。不是 Docker VHD 或构建缓存所在卷的定位结果。                  |
| `findings` | 固定信号码，例如 `low_system_disk`、`not_ready_gateway`、`service_inventory_command_timeout`。不包含客户场景、endpoint、运行名称或原始错误。 |
| `limits`   | 此次单命令超时、容器上限和 metadata-only 标识。                                                                                              |

- 主机卷可用低于 5 GiB **或** 5% 时告警；这是运维阈值，不是已证实卡顿原因。
- Docker 不响应时不继续 inspect、不声称应用正常/异常。Daemon 响应但 inventory 超时则保留 daemon 响应事实，应用状态未知。
- 健康状态 unhealthy 或非 running、缺少任一核心服务为 fail。starting/未配置 healthcheck 为 warn，不能把 running 当作业务可用。
- 历史 restart_count/OOM 标志为风险提示，不证明当前循环重启或当前发生内存耗尽；这些字段也不是历史事件的完整记录。
- 没有 HTTP 探测、数据库完整性检查、模型调用、目标请求或测试结果检查。真正的页面/接口/迁移验收仍须独立进行。

## 服务健康与启动顺序

生产与开发 Compose 模板新增以下独立健康检查。**诊断脚本本身仍是 metadata-only，不发送 HTTP；这里的 HTTP 请求是 Docker 定期执行的另一个机制。**

| 服务     | 最小探测                                                                             | 能证明什么 / 不能证明什么                                                                                                                                                                          |
| -------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| gateway  | 镜像自带 Python HTTPConnection → `127.0.0.1:8001/health`，socket 超时 2 秒，必须 200 | ASGI HTTP 入口响应；不读取 DB/配置、不校验迁移/权限/模型/目标。直连不使用代理，不跟随重定向，不读取响应正文。                                                                                      |
| frontend | 镜像自带 Node HTTP → `127.0.0.1:3000/login`，总时限 3 秒，必须 200                   | 已有匿名登录页能返回 HTTP 头；不证明资源加载、客户端水合、登录成功或全部页面可用。使用独立无池化连接，不带凭据、不跟随重定向、不读取响应正文。开发模式首个请求可能触发正常路由编译，但不安装依赖。 |
| nginx    | 镜像自带 BusyBox wget → `127.0.0.1:2026/nginx-health`，2 秒超时、一次尝试            | 显式关闭 wget 代理；代理自身固定 `ok` 文本响应；不依赖上游，不暴露业务内容，也不证明 gateway/frontend 正常。该固定公开端点不记录访问日志。                                                         |

- 均为 exec-form CMD，无 shell、包安装、运行配置读取、凭据输出、日志抓取、模型调用或被测组件请求。失败无原始异常/正文输出；现有 `/health` 服务访问日志不在此声明中被关闭。
- 周期 30 秒、Docker 强制时限 5 秒、连续失败 3 次标记异常；gateway/frontend 启动宽限 60 秒、nginx 10 秒。宽限期不是“强制等待后才探测”，也不是启动成功保证。
- nginx 的 `depends_on` 改为两路 `service_healthy`，仅在初始 Compose 启动/创建时等待。没有依赖重启级联、轮询修复、自动重发或生产编排控制器。
- 既有 `restart: unless-stopped` 保持不变；它针对进程退出/引擎恢复，不因为 unhealthy 状态自行重启仍在运行的容器。不要在 healthcheck 中 kill 主进程、重启 Docker 或重发评测。
- 修改模板不会更新既有容器，也不修改私有部署覆盖。应用前先检查配置/挂载与备份；只针对本项目受影响服务重建，随后逐项确认实际 Config.Healthcheck、状态和数据保留，不直接执行全栈 down/up。
- 这是分层的最小 HTTP/进程信号，不是完整就绪探针、业务验收、长时稳定性保证或 Desktop 卡顿根因修复。

离线回归 `backend/tests/test_compose_service_health.py` 覆盖两个模板、初始依赖和精确探测源码的非 200/重定向/连接错误/总时限/静默失败；Node 用合成 VM，不碰网络。实际 Docker 执行、nginx 语法、故障到 unhealthy 的状态转换和正式环境应用仍需要独立记录，不能拿配置测试当部署成功。

## 恢复决策与数据保护

1. 先保存本地、受控的诊断结果；不用上传原始 inspect/log/Compose/env 来排障。
2. 应用异常且 daemon 正常：先定位对应服务，按已有在线备份/配置哈希/挂载核验流程更新，不重启所有项目。
3. daemon 无响应：结合主机资源与受控 Desktop 日志进一步调查；经授权后可正常重启，失败时再审慎选择官方恢复方式。此脚本绝不会自行执行。
4. 磁盘告警：先确认 Docker 存储位置、哪些文件可清理或是否需要迁移；不自动 prune、删除卷/镜像、迁移 VHD 或改资源配置。
5. 恢复后检查原账号、配置、数据卷及迁移 ledger；不能自动重新发送未知送达的评测请求。

诊断不会读取配置、请求内容、环境变量集合、挂载源、镜像名、容器名、日志、凭据或客户指标，也不会将诊断结果自动上传至 GitHub。脚本访问 `SystemRoot` 仅用于确定 Windows 系统卷，不输出其值。

## 测试与证据界限

`backend/tests/test_docker_health.py` 先红后绿，使用合成元数据覆盖：健康/缺失服务、无 healthcheck、历史重启/OOM、低磁盘/未知磁盘、项目/ID/数量/输出边界、固定错误码、单命令超时、共享截止时间、无 shell、无敏感原文和 CLI 退出码。

本机实际只读运行已成功，能够区分 daemon 正常与服务观测告警；实际运行时的资源数字保留在本地而不写入此公开文档。测试不是长期负载稳定性证明，也不是全部 GitHub Actions 通过证明。

### 隔离运行时验证（2026-11-08）

除配置单测外，使用现有 gateway/frontend/nginx 镜像创建无网络、无挂载的临时容器，执行真实探测命令：Gateway 6 种、frontend 7 种合成 HTTP 场景（200、非 200/重定向、拒绝连接，以及前端不响应的总时限），均符合预期且不输出原始内容；nginx 完成实际语法检查和本地固定端点探测。两个独立合成服务器也观察到 Docker healthy → unhealthy → healthy，期间进程重启数为 0。状态转换测试缩短了周期，不能冒充生产 30 秒配置的持续运行证明。

这些测试不挂业务卷、不修改现有服务；验证收据只留本机。每个新提交仍需独立核对 CI，本地实际应用也需另有收据，不能把合成容器结果当成业务部署或根因修复。

## 生产 Gateway 启动不做依赖同步

生产 Compose 覆盖命令同镜像保持 `uv run --no-sync uvicorn ...`，使用构建时安装的依赖；开发入口保留其同步/热重载设计。本轮只修正生产覆盖遗漏，不证明它导致了此前本地卡顿；本地私有服务原本直接运行虚拟环境 Python，不需为此重复重建。

## 镜像清理与空间维护

1. 构建前先看系统盘与 Docker 状态，禁止反复堆积同一功能镜像作为“排障”。镜像占用的是磁盘，不能据此认定运行内存不足。
2. 新镜像只在升级完成、健康/入口/既有账号和配置数据核验后替换旧镜像；验证前保留回退能力。
3. 用 `docker image ls`、`docker ps -a` 与必要的定向 inspect 确认本项目镜像和**所有**容器引用，含已停止容器。不要输出环境、凭据或私有挂载原文。
4. 只对确认属于本项目且无引用的旧镜像执行 `docker image rm <exact-reference>`，不使用 `--force`。清理后再次核对服务健康。当前镜像必须保留。
5. 构建产生的悬空镜像仅在可证明属于本次 DevPilot 构建且无引用时清理，不使用全局 dangling prune。未知归属保留并提示。
6. 已停止验证容器引用的镜像不能先删。若容器本身也确已退役，先核对精确 ID、停止状态、项目归属、挂载是否只读源码、可写层是否仅为可丢弃测试产物及替代测试环境是否已验证；有业务数据或未知用途则保留。仅用 `docker container rm <exact-id>`，不加 `--force` 或 `--volumes`；随后重新枚举全部容器引用，再考虑镜像。不得顺手 `container prune` 或删除卷、账号配置、其他项目/全局 build cache。
7. 镜像可能共享层，显示体积不能简单相加当作实际释放空间；Docker Desktop 虚拟磁盘未必立即把空间归还宿主。压缩/迁移 VHDX 是单独运维步骤，本轮未执行。
8. 该步骤是**每次成功升级的收尾项**，不是等磁盘再次告警才做。记录本次保留的当前版本、已精确删除的旧引用、因停止容器引用或未知归属而保留的项目镜像，以及清理后的服务检查结果。清理失败不能隐瞒，也不能因此强制删除或放大范围；未构建/未升级时不得声称完成了一次新的镜像清理。

9. `docker system df` 的 `RECLAIMABLE` 是汇总估算，不是删除许可；即使显示 100% 也要逐项检查全部容器引用、项目归属、缓存用途和回退需求。无标签镜像仍可能被停止容器引用，不能据此删除。

### 隔离测试容器的内存收尾

- 会话开始记录原先状态与本次启动的专用 CI 容器；复用已经验证的依赖缓存，不反复新建同功能容器/镜像。
- **所有测试进程、集成请求与子进程结束后**，停止本次启动的测试容器，包括对应 PostgreSQL/Redis。不因名称相似而停止原先就在运行的服务，也不在回归进行中抢先停库。
- 有复用价值的停止容器不是“无用容器”，不占运行态 RAM，可保留依赖/测试库；过期的验证容器另按上节核验退役。只删除本次创建且已留存必要收据的临时源码/构建目录，不清未知缓存或历史证据。
- 镜像和停止容器的可写层主要占**磁盘**；停止运行中的测试服务才针对其运行内存。Docker Desktop/WSL 后台内存与 VHDX 回收是另一层问题，不为清理而重启 Desktop 或擅自压缩磁盘。
- 这是一项每次测试/成功升级后的主动收尾约定；当前没有安装定时自动删除或全局清理任务，避免错误地停止测试/业务或破坏回退。

此前一次本地核对（2026-11-08，历史记录）：用户清理后系统盘已超过低空间阈值，服务健康且无容器重启/OOM；删除了三个无容器引用的旧 DevPilot 镜像，保留当前镜像、旧验证容器仍引用的镜像和其他项目。没有 prune、卷操作或 Docker 重启。该记录不代表低空间就是历史卡顿根因。

本次已核验维护（2026-11-08，运行 SHA `0fd689da83a4ac7646250447fb6d044599a823c5`）：升级和账号/数据/页面验收通过后，精确删除被替代的 `qa-retests-3a5cd38fc99d` gateway/frontend 两个旧镜像标签；仍被停止验证容器引用的 `f4588c3` 镜像保留。再次检查四个服务均 healthy，无新增容器重启/OOM。不删除容器、数据卷、其他项目或全局构建缓存；未检查未知 dangling 的归属，也未压缩 VHDX。[完整记录](DevPilot_Local_Recovery_and_Upgrade.md)。不要将本次两项与前次历史清理混为一次操作。

English: remove only positively identified, unreferenced DevPilot images after a verified upgrade. Include stopped-container references, never force/prune globally, and preserve volumes/unrelated projects. Layer sharing and Docker Desktop virtual disks mean tag sizes are not reclaimed-host-space evidence.

### 2026-11-09：旧验证容器及旧镜像精确退役

在新的隔离后端完整回归与前端生产构建确认可用后，核对下列旧验证容器均已停止、非业务 Compose 成员、network none、仅只读挂载源码且无业务数据卷，精确退役：

- `devpilot-verify-frontend`，容器 ID `9147a830017517fe0202939c6b7823759a36a6b40aee21d9fdbac6f4398407d2`。
- `devpilot-verify-backend`，容器 ID `70c611b2c6a0aab14a6452d1071bdddca9b97e0b377bf0de12f051ea56f27a30`。

随后重新枚举**全部容器（含停止）**的镜像 ID 引用，确认不再被引用后，精确删除 `devpilot-local/frontend:f4588c3`（image ID `05460fdf4bd3…`）和 `devpilot-local/gateway:f4588c3`（`2d1f74f887b6…`）。这是对上节“仍被旧验证容器引用”的后续处理，不改写 2026-11-08 当时的事实。

保留当前部署 `devpilot-local/frontend:criteria-0fd689da83a4`、`devpilot-local/gateway:criteria-0fd689da83a4` 及其运行容器；没有新建/替换业务服务。其他项目、数据卷、账号/配置、可复用 CI 依赖缓存不动。没有 force、全局 prune、删卷、清全局 build cache 或重启 Docker Desktop；不以镜像标称大小相加声称实际释放空间，不声称宿主 VHDX 已压缩。没有安装定时自动清理任务。

本轮测试收尾（2026-11-09 01:10，Asia/Shanghai）：所有测试进程结束、收据保存后，删除本次 `/verification/20261109-d2a58a3-baseline` 临时源码/构建目录及临时 Node 副本；先核对绝对路径与活动进程，并验证 `/workspace` 共享缓存探针未改变。宿主本轮临时源码 tar 已移除，必要日志与哈希收据保留在 ignored 验证目录。

已按精确 ID 停止本次启动的 `devpilot-ci-python`、`devpilot-ci-node`、`devpilot-ci-postgres`、`devpilot-ci-redis`，四者最终均为 exited，保留可复用依赖及专用测试缓存，不再作为运行测试服务占用 RAM。全部其他容器的 ID、镜像与运行/停止状态前后相同。最后 `python scripts/docker_health.py --project devpilot-local` 返回 `ok`、findings 为空；gateway/frontend/nginx/redis 四个业务服务均 running/healthy、restart=0、OOM=false。该结果只证明上述检查范围，不证明宿主内存立即全额归还或 VHDX 缩小。

### 2026-11-09 02:06：合成链路回归后的资源收尾

这是上述 01:10 收尾之后的一次独立开发轮次，不是新的业务部署或镜像升级。API→实际 Worker 八项合成回归及完整后端 **12,125 passed / 19 skipped / 11 deselected** 结束，留存日志/manifest/环境修复证据后：

- 确认没有活动测试/子进程，精确移除 `/verification/20261109-qa-chain-d2a58a3` 临时源码、独立 venv 与 Node 副本；共享 `/workspace` 依赖/源码保留。三个 editable 安装文件在快照删除前后 SHA-256 一致，稳定路径导入再次通过。
- 精确停止本轮启动的 `devpilot-ci-python`（`972fbed64519…`）、`devpilot-ci-postgres`（`f73ac6683a6c…`）、`devpilot-ci-redis`（`9130a4c5a3b6…`）。Node CI 本轮没有启动，保持 exited；最终四个 CI 容器均停止，保留可复用缓存，不占运行态服务内存。
- 核验宿主绝对路径和临时文件白名单后，删除本轮源码 tar、Node 副本与辅助脚本目录；证据已独立保存在 ignored `.deer-flow/verification/20261109/evidence/qa-chain/`，未清理历史证据或未知缓存。
- 当前两个 `criteria-0fd689da83a4` 业务镜像仍被现役容器引用，未删除；清单无悬空镜像，因此这轮没有额外镜像删除。上一轮两个旧容器/旧镜像的精确退役记录不重复计数。
- 所有其他容器的 ID、镜像、运行/停止状态、重启/OOM 信息前后相同。最终只读 `docker_health.py --project devpilot-local` 为 **ok / findings 空**，gateway/frontend/nginx/redis 四个业务服务均 healthy、restart=0、OOM=false。

未删业务容器或任何数据卷，未全局 prune、强制删除、清全局构建缓存、重启 Desktop、改生产配置或启用真实模型/目标。停止测试服务与移除临时文件不证明宿主内存立即全额归还，也不证明 VHDX 已压缩；没有安装后台定时删除任务。

### 2026-11-09 02:14：当前请求的独立资源复查

本轮只读复查全部容器的镜像 ID 引用、镜像清单、可写层大小、瞬时内存与项目健康，没有启动测试、构建镜像、部署或执行删除。四个 DevPilot 业务容器均 running/healthy、restart=0、OOM=false；四个 CI 容器均为 exited，保留可复用的 Python/Node 依赖与专用测试数据，不占运行态服务 RAM。

当前两个 DevPilot 自建镜像均被现役容器引用，没有无引用的 DevPilot 标签镜像候选。本次显式 `--filter dangling=true` 另发现一个无标签镜像，仍被其他项目的停止容器引用，因此保留。这是完整引用复查的新结果；此前“清单无悬空镜像”仅描述当时清单，不能作为当前全局无 dangling 的保证。未核实来源的构建缓存、所有卷、其他项目以及当前/必要回退资源均不动。

本机 `docker system df` 同时报告所有镜像 active 与 100% reclaimable；其汇总不作为可删判断。只读项目诊断仍为 **ok / findings 空**。本轮零删除、零资源启停，不能把前轮两个旧容器/旧镜像的退役重复计数为本轮成果。详细数字与 SHA-256 收据仅保存在 ignored 本地验证目录，不以镜像显示大小、停止容器或这次快照推断宿主已释放 RAM、磁盘或 VHDX 空间。

### 2026-11-09：独立复核后端回归后的资源收尾

独立复核候选全量 **12,191 passed / 19 skipped / 11 deselected**、Ruff 1,227 文件及最终 Docker/文档契约 **91 passed**（与全量重叠，不相加）结束后，28 份日志/环境收据已复制并逐项 SHA-256 校验，保留初次失败而不是只保留最后一次通过。另有本轮十二份 Markdown 的 Prettier 检查；不是前端构建/单测/浏览器重跑。

- 确认 Python CI 仅剩闲置保活进程，无活动测试；精确移除 `/verification/20261109-independent-review-d2a58a3` 独占源码/venv/Node/格式工具和七个本轮辅助文件。共享三个 editable `.pth` 哈希、51 个共享 launcher 哈希保持不变，稳定 `/workspace` 导入再次通过；保留可复用依赖。
- 仅停止本轮启动的 Python（`972fbed64519…`）、PostgreSQL（`f73ac6683a6c…`）、Redis（`9130a4c5a3b6…`）CI 容器；Node 本轮始终未启动。最终四个 CI 容器均 exited，测试服务不再处于运行态；不按停止前的瞬时内存推算宿主立即释放量。
- 全容器镜像引用复查没有无引用 DevPilot 镜像候选。两个 `criteria-0fd689da83a4` 现役镜像仍被业务容器引用；无标签镜像仍由其他项目停止容器引用，保留。本轮没有构建或删除镜像、删除容器/卷、全局 prune、清全局构建缓存或重启 Desktop；不能重复计数前轮退役的两个旧容器/镜像。
- 收尾前后全部其他容器的 ID、镜像、运行/停止、restart/OOM 信息一致。最后项目诊断 **ok / findings 空**，frontend/gateway/nginx/redis 均 running/healthy、restart=0、OOM=false。没有改账号/配置/挂载、迁移生产或启用真实模型/目标。

宿主本轮临时 Node/源码 tar/脚本目录按“先保存最终 manifest 并校验，再核对精确路径删除”的顺序收尾；必要证据保留于 ignored `.deer-flow/verification/20261109/evidence/independent-review/`。这些动作不证明 VHDX 压缩或宿主 RAM 全额归还；没有后台定时自动删除任务。

### 2026-11-09：独立复核 UI 验证后的资源收尾

本轮仅启动既有 Node CI；最终 frontend Prettier、lint/typecheck、1,125 项单测、生产构建、完整模拟浏览器 206 项及独立登录/设置恢复 2 项均已有各自通过证据。定向用例与全量有重叠，不相加；模拟 API 不代表真实多账号联调或用户验收。没有依赖安装、新镜像、业务部署或真实模型/目标调用。

- 先将 37 份日志/收据复制到宿主并逐项 SHA-256 校验，包含初次失败；833 份源码/公开契约/指南与隔离快照清单无差异。之后仅追加本文等资源收尾文字，不冒称重新运行完整套件。
- 确认没有活动测试或 Next 服务后，按已核对的绝对路径移除 `/verification/review-ui-20261109-d2a58a3` 独占源码/构建目录、本轮辅助文件及 Docker 中的证据临时副本。宿主本轮 staging 目录亦在证据独立保存并校验后精确移除。
- 共享 Node 依赖及 Chromium 缓存保留。清理前后五个明确的 Node 缓存标识文件哈希一致，仅证明这些标识，不能扩大为整个依赖树审计。
- 仅按完整 ID 停止本轮启动的 `devpilot-ci-node`（`72814c38e51bd2306af003be8c1c8ae3bced9c85fb72894b6f75d1ad22fc5667`）；Python/PostgreSQL/Redis CI 保持停止。四个测试容器最终均 exited；保留可复用依赖和专用测试数据，不让测试服务继续处于运行态。
- 全部其他 13 个容器的 ID、镜像、运行/停止、restart/OOM 信息前后一致，镜像引用清单不变。没有无引用的 DevPilot 镜像候选；其他项目停止容器引用的无标签镜像保留。本轮删除镜像/容器/卷均为零，不重复计数此前旧资源退役。
- 最终项目只读诊断为 **ok / findings 空**，frontend/gateway/nginx/redis 四业务服务均 running/healthy、restart=0、OOM=false。账号、配置、业务挂载及当前部署未改；无全局 prune、force、删卷、全局构建缓存清理或 Desktop 重启。

本轮证据独立保存在 ignored `.deer-flow/verification/20261109/evidence/review-ui/`。停止测试服务、删除临时文件并不证明宿主 RAM 立即全额归还、镜像标称大小等于释放空间或 VHDX 已压缩；未安装后台自动删除任务。

### 2026-11-09：独立评估修订完整回归后的资源收尾

本轮完整后端 **12,231 passed / 19 skipped / 11 deselected** 完成后，先导出 19 份测试/环境日志及 JSON 并逐项验 SHA-256，保留早期失败；另保存清理、只读诊断、源码与资源对比收据。未构建镜像或升级业务部署。

- 确认无活动测试进程后，仅删除 `/verification/20261109-assessment-d2a58a3` 独占源码/venv/Node/格式工具及九个精确列名的 `/tmp` 辅助文件；宿主本轮 staging 按绝对路径检查后精确删除。共享三个 editable marker 与 51 个 launcher 在清理前后哈希未变，稳定路径导入再次通过；保留可复用 CI 容器/依赖，不是整个缓存树审计。
- 19 份证据已导出并验真后，仅删除本轮对应 Docker 日志/JSON/归档及清理回执副本，共 22 个精确文件；宿主必要证据保留。没有扫描删除其他轮次日志或全局临时目录。专用 CI PostgreSQL 的 assessment 临时数据库数为 0。
- 仅按精确 ID 停止本次启动的 Python（`972fbed64519…`）、PostgreSQL（`f73ac6683a6c…`）和 Redis（`9130a4c5a3b6…`）CI；Node 始终停止。停止命令退出码为 0，但脚本随后对 stdout 的精确集合断言失败，后续状态改用独立只读 inspect 核对，没有重复删除或停止。Python CI 为 exit=137、OOM=false，不把它记为优雅退出或 OOM；没有活动测试因此中断。
- 全部 14 容器的 ID/名称/镜像/运行或停止/restart/OOM 签名与本轮测试前一致，镜像 Repository/Tag/ID/Digest/Size 清单不变。两个现役 DevPilot 镜像被业务容器引用；无可安全删除的无引用 DevPilot 镜像。一个无标签镜像仍被其他项目停止容器引用，保留。本轮镜像、容器和卷删除数均为 0，不重复计数历史退役成果。
- 最终 `docker_health.py --project devpilot-local` 为 **ok / findings 空**；gateway/frontend/nginx/redis 四业务服务均 healthy、restart=0、OOM=false。此为元数据与最小健康信号，不是数据库内容/模型/目标验收，也不证明宿主 RAM 已全额归还或 VHDX 缩小。

不全局 prune、不强制删除、不清未经归属验证的构建缓存、不删业务容器/卷、不重启 Desktop、不改生产账号/配置/挂载、不启用后台自动清理。每轮“导出证据 → 精确清理独占临时资源 → 停本轮 CI → 复查业务”的约束继续执行；可复用 stopped CI 和依赖不是自动判定的垃圾。证据位于 ignored `.deer-flow/verification/20261109/evidence/assessment/`。

### 2026-11-09：独立全样本评估 UI 验证后的资源收尾

本轮只有既有 Node CI 被启动；完整前端 1,152 单测、210 模拟浏览器与 2 登录恢复、生产构建及格式/静态门禁完成。没有构建镜像、依赖下载、业务部署、生产迁移或真实模型/目标调用。

- 先校验 834 份公开源码/测试/契约/选定指南与独占快照无差异，将 30 份 Docker 日志/JSON（含初次失败）导出到宿主并逐项核验 SHA-256。必要证据保存在 ignored `.deer-flow/verification/20261109/evidence/assessment-ui/`。
- 浏览器结束即停止两个 loopback Next 站点；最终确认无活动测试进程后，按核对过的绝对路径和清理计划 hash 删除 `/verification/assessment-ui-20261109-d2a58a3`、12 个精确辅助文件、30 份已备份日志/JSON 及两份临时清单；最后一份清理回执复制到宿主验 hash 后亦从 Docker 删除。宿主仅含源码 tar/manifest 的 staging 经绝对路径与 reparse-point 检查后精确删除，必要证据保留。
- 保留共享 Node/Chromium 缓存、所有卷及可复用 CI 容器；五个明确依赖标识哈希清理前后一致，不外推为整个依赖树审计。构建使用同盘硬链接，不放宽 Turbopack 根目录，也不在服务启动时构建。
- 仅按完整 ID 停止本轮 `devpilot-ci-node`（`72814c38e51bd2306af003be8c1c8ae3bced9c85fb72894b6f75d1ad22fc5667`）；Python/PostgreSQL/Redis CI 保持停止。Node 最终 exit=137、OOM=false；没有活动测试被中断，不声称优雅退出。
- 全部 14 容器 ID/名称/镜像/状态/restart/OOM 与测试前一致；9 行镜像 Repository/Tag/ID/Digest/Size 清单未变。无可安全删除的无引用 DevPilot 镜像；一个无标签镜像被其他项目停止容器引用而保留。本轮镜像、容器、卷删除数均为零，不为了“看起来整洁”删除共享资源或回退能力。
- 最终只读项目诊断 **ok / findings 空**，frontend/gateway/nginx/redis 均 running/healthy、restart=0、OOM=false。生产账号、配置、业务数据、挂载及运行版本未更改。

以上维护不证明 Docker VM 的 RAM 已立即全额归还或宿主 VHDX 已压缩。镜像/停止容器主要占磁盘，运行中的测试服务才带来持续运行态开销；不使用全局 prune/force、卷删除、其他项目清理、Desktop 重启或后台自动删除。资源收尾后的更改只含文档/ignored 证据，不冒称重跑完整套件。

### 2026-11-09 06:51：遗留基线测试的归档与精确收尾

接手时本轮后端基线仍在运行，先等待其自然结束，再归档日志；结果为 **12,224 passed / 37 skipped / 40 warnings，537.19s**。这是 2,478 份公开源码快照的变更前基线，不是随后尚未完成的独立报告/复测绑定模块的通过证明。开发中的工作区文件保留，未提交、部署或启用执行。

- 四份 Docker 日志/JSON 已导出并逐项核对大小及 SHA-256；清理前验证全部 2,478 份快照源码与本轮源包一致、没有仍使用快照的进程和嵌套挂载。
- 仅精确删除本轮独占 Docker 快照、四个临时辅助文件、已归档的四份结果副本，以及宿主六文件 staging。保留基线源码清单、失败/成功日志、辅助脚本与清理收据。三个共享 editable 文件及 51 个共享 launcher 的明确哈希清理前后相同，不外推为整个依赖缓存审计。
- 仅停止本轮从 exited 启动的 Python/PostgreSQL/Redis CI；Node CI 始终停止。四个 CI 最终均 exited，仍保留可复用容器和共享依赖；没有本轮仍运行的快照测试进程或自动删除服务。
- 独立复核全部 **14** 个容器的 ID/镜像/运行或停止/restart/OOM 签名恢复本轮开始状态，九行镜像标签清单不变。无可安全删除的闲置 DevPilot 镜像；唯一无标签镜像仍被 `aiqa-redis` 引用，保留。镜像/容器/卷零删除，未触及其他项目。
- 最终仅四个 DevPilot 业务容器及原有其他项目容器运行；业务四服务 healthy，只读诊断 `ok`。停止 CI 消除了本轮 CI 的持续运行占用，但未测量宿主实际 RAM 释放或 VHDX 压缩量，也未做 Docker Desktop 重启、prune 或构建缓存清理。

本地收据位于忽略目录 `.deer-flow/verification/20261109/evidence/independent-archives/`；其中基线与预期的红灯失败分别保留，不能把资源收尾说成新功能交付或当前工作区全量通过。

### 2026-11-09 07:45：独立历史报告/复测后端验证后的精确收尾

本轮完整后端离线回归 **12,284 passed / 26 skipped / 11 deselected / 40 warnings，593.12s** 后才进行清理；没有中断测试。候选 `eval_0012` 未部署，现有业务版本、账号、配置和挂载不变；没有构建镜像、下载依赖、真实模型/目标调用或生产迁移。

- 先核对运行/测试源码与测试快照逐项 SHA-256 一致，后补文档单独格式检查/同步；清理前最终 **2,484** 份公开文件与宿主清单相同。初始 **2,480** 份清单单独保留，不用最终清单覆盖最初工作区证据。
- 将全部 **19** 份 Docker 日志/JSON（包括早期失败）导出到宿主并逐项核对大小和 SHA-256；确认无使用快照的进程和嵌套挂载后，才精确删除 `/verification/20261109-independent-archives-v2-d2a58a3`、四个本轮辅助文件与十九份已验真结果副本。宿主六文件 staging 经绝对路径/reparse-point 检查后删除，必要日志、源码清单、脚本和收据保留。
- 共享依赖/卷不删除；三份 editable 与 **51** 个 launcher 的明确哈希清理前后相同，不外推为整个缓存树审计。只读确认 `devpilot_ind_archive_test_` 临时测试数据库剩余数为 **0**，没有对业务数据库做清理。
- 仅按完整 ID 停止本轮从 exited 启动的 Python/PostgreSQL/Redis CI；Node CI 始终停止，四个 CI 最终均 exited。Python CI 最后 exit=137、OOM=false，PostgreSQL/Redis exit=0；测试在 stop 前已经结束，不声称 Python 优雅退出。可复用 stopped 容器和缓存保留，不因“停止/无标签/旧”直接判为垃圾。
- 独立复核全部 **14** 个容器的 ID/名称/镜像/运行或停止/restart/OOM 签名恢复测试前状态；**9 行**镜像标签清单不变。没有无引用的 DevPilot 镜像；唯一无标签镜像被其他项目容器引用而保留。本轮镜像/容器/卷删除数均为 **0**，不为了凑清理数字损失回退或共享资源。
- 最终仅四个 DevPilot 业务容器和原有其他项目容器运行；业务四服务 running/healthy、restart=0、OOM=false，只读诊断 **ok / findings 空**。这是最小 HTTP/进程健康，不替代业务、数据库或模型/目标验收。

证据位于 ignored `.deer-flow/verification/20261109/evidence/independent-archives-v2/`，含导出/清理/停止/独立复核回执；两次收尾检查命令问题（PowerShell 引号解析、沙箱日志写入拒绝）也单独登记，改用独立脚本和获准权限后通过，不混为功能测试失败或偷偷重做删除。资源收尾后仅追加文档/ignored 证据，格式检查单独执行，不冒称再次运行完整后端或前端套件。

持续遵循“导出并验真 → 精确清理本轮独占临时资源 → 停本轮 CI → 复核业务”的约束。镜像和停止容器主要占磁盘，运行容器带来持续内存占用；未测量宿主实际 RAM 归还量或 VHDX 缩小量。没有 global prune、force 删除、卷删除、未验证归属的构建缓存清理、其他项目清理、Desktop 重启或后台自动删除。

### 2026-11-09 08:50：独立历史档案 UI 验证后的精确收尾

本轮前端最终单测 **1,164 passed / 148 文件**、完整模拟浏览器 **214 passed**、登录恢复 **2 passed**；浏览器均零自动重试。lint/typecheck、生产构建及完整前端 Prettier 分别通过。后端本轮未重跑，逐项复核 **1,267 份** backend 非 Markdown 源码与前轮 12,284 passed 的 manifest 相同；候选 `eval_0012` 未部署，运行仍为 `eval_0009`。

- 最终 **840** 份公共前端/合同/指定指南与测试快照逐项 SHA-256 一致；导出全部 **34** 份日志/JSON/首次失败浏览器 artifact 后，逐项对比 Docker 与宿主大小和 SHA-256，保留红灯与修复后结果。
- 确认没有使用快照的进程或嵌套挂载后，仅删除本轮独占 `/verification/independent-archive-ui-20261109-d2a58a3`、七个 helper、source tar 与已验真的结果副本。宿主单文件 staging 在绝对工作区边界和 reparse-point 检查后删除；ignored 证据保留。
- 两个本轮前端测试服务先按确切进程组停止；仅按完整容器 ID 停止本轮从 exited 启动的 Node CI。Python/PostgreSQL/Redis CI 全程未启动，四个 CI 最终均 exited。没有新建镜像或容器，也未删除镜像、容器、卷或共享依赖；五个明确 Node 缓存标识的哈希清理前后相同，不声称整个缓存树已审计。
- 独立复核全部 **14** 容器 ID/名称/镜像/运行或停止/restart/OOM 签名恢复测试前状态，**9 行**镜像标签清单不变。不存在可安全删除的无引用 DevPilot 镜像；其他项目和被引用的无标签镜像保留。业务四服务 running/healthy、restart=0、OOM=false，只读诊断 **ok / findings 空**。

证据位于 ignored `.deer-flow/verification/20261109/evidence/independent-archive-ui/`。收尾命令的 Windows 参数长度错误与权限审核超时单独记录，修正传输方式后通过，不混为应用回归失败。收尾后仅更新文档和证据，格式检查单独执行；没有真实模型/目标调用、生产迁移、Desktop 重启、global prune、force 或 VHDX 压缩，不声称测得宿主 RAM 归还量。最小服务健康不等于业务或用户最终验收。
