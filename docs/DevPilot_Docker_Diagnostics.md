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
