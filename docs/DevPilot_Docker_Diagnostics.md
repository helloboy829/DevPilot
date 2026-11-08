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

| 字段 | 含义与边界 |
| --- | --- |
| `status` | `ok`、`warn`、`fail`。warn 的退出码仍为 0；fail 为 1。参数无效由 CLI 返回 2。 |
| `docker` | 仅 Docker 是否响应及可用 CPU/总内存数；错误为固定 reason code，不包含 stderr/上下文路径。 |
| `services` | 固定服务的匿名实例数组，仅 state/health/restart_count/oom_killed/exit_code。尚未可靠查询为 null；可靠查得无实例才为 []。 |
| `storage` | 工作区卷与系统卷的容量/剩余字节，不输出路径。不知道就是 unknown，绝不伪造为 0。不是 Docker VHD 或构建缓存所在卷的定位结果。 |
| `findings` | 固定信号码，例如 `low_system_disk`、`not_ready_gateway`、`service_inventory_command_timeout`。不包含客户场景、endpoint、运行名称或原始错误。 |
| `limits` | 此次单命令超时、容器上限和 metadata-only 标识。 |

- 主机卷可用低于 5 GiB **或** 5% 时告警；这是运维阈值，不是已证实卡顿原因。
- Docker 不响应时不继续 inspect、不声称应用正常/异常。Daemon 响应但 inventory 超时则保留 daemon 响应事实，应用状态未知。
- 健康状态 unhealthy 或非 running、缺少任一核心服务为 fail。starting/未配置 healthcheck 为 warn，不能把 running 当作业务可用。
- 历史 restart_count/OOM 标志为风险提示，不证明当前循环重启或当前发生内存耗尽；这些字段也不是历史事件的完整记录。
- 没有 HTTP 探测、数据库完整性检查、模型调用、目标请求或测试结果检查。真正的页面/接口/迁移验收仍须独立进行。

## 服务健康与启动顺序

生产与开发 Compose 模板新增以下独立健康检查。**诊断脚本本身仍是 metadata-only，不发送 HTTP；这里的 HTTP 请求是 Docker 定期执行的另一个机制。**

| 服务 | 最小探测 | 能证明什么 / 不能证明什么 |
| --- | --- | --- |
| gateway | 镜像自带 Python HTTPConnection → `127.0.0.1:8001/health`，socket 超时 2 秒，必须 200 | ASGI HTTP 入口响应；不读取 DB/配置、不校验迁移/权限/模型/目标。直连不使用代理，不跟随重定向，不读取响应正文。 |
| frontend | 镜像自带 Node HTTP → `127.0.0.1:3000/login`，总时限 3 秒，必须 200 | 已有匿名登录页能返回 HTTP 头；不证明资源加载、客户端水合、登录成功或全部页面可用。使用独立无池化连接，不带凭据、不跟随重定向、不读取响应正文。开发模式首个请求可能触发正常路由编译，但不安装依赖。 |
| nginx | 镜像自带 BusyBox wget → `127.0.0.1:2026/nginx-health`，2 秒超时、一次尝试 | 显式关闭 wget 代理；代理自身固定 `ok` 文本响应；不依赖上游，不暴露业务内容，也不证明 gateway/frontend 正常。该固定公开端点不记录访问日志。 |

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
6. 已停止验证容器引用的镜像暂不删；清理容器本身须另核实其用途和数据，不能顺手 `container prune`。不得删除卷、账号配置、其他项目或全局 build cache。
7. 镜像可能共享层，显示体积不能简单相加当作实际释放空间；Docker Desktop 虚拟磁盘未必立即把空间归还宿主。压缩/迁移 VHDX 是单独运维步骤，本轮未执行。
8. 该步骤是**每次成功升级的收尾项**，不是等磁盘再次告警才做。记录本次保留的当前版本、已精确删除的旧引用、因停止容器引用或未知归属而保留的项目镜像，以及清理后的服务检查结果。清理失败不能隐瞒，也不能因此强制删除或放大范围；未构建/未升级时不得声称完成了一次新的镜像清理。

此前一次本地核对（2026-11-08，历史记录）：用户清理后系统盘已超过低空间阈值，服务健康且无容器重启/OOM；删除了三个无容器引用的旧 DevPilot 镜像，保留当前镜像、旧验证容器仍引用的镜像和其他项目。没有 prune、卷操作或 Docker 重启。该记录不代表低空间就是历史卡顿根因。

本次已核验维护（2026-11-08，运行 SHA `0fd689da83a4ac7646250447fb6d044599a823c5`）：升级和账号/数据/页面验收通过后，精确删除被替代的 `qa-retests-3a5cd38fc99d` gateway/frontend 两个旧镜像标签；仍被停止验证容器引用的 `f4588c3` 镜像保留。再次检查四个服务均 healthy，无新增容器重启/OOM。不删除容器、数据卷、其他项目或全局构建缓存；未检查未知 dangling 的归属，也未压缩 VHDX。[完整记录](DevPilot_Local_Recovery_and_Upgrade.md)。不要将本次两项与前次历史清理混为一次操作。

English: remove only positively identified, unreferenced DevPilot images after a verified upgrade. Include stopped-container references, never force/prune globally, and preserve volumes/unrelated projects. Layer sharing and Docker Desktop virtual disks mean tag sizes are not reclaimed-host-space evidence.
