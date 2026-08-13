# DevPilot 部署与运维设计 v1.0

## 0. 文档说明

本文档定义 DevPilot 的部署架构、环境规划、CI/CD、监控告警与运维规范。DevPilot 为 SaaS 部署形态，本地开发用 Docker Compose 一键起全套。

## 1. 部署架构总览

```text
                    CDN / WAF / 负载均衡
                            |
                       Next.js (前端，静态 + SSR)
                            |
                       FastAPI (API 网关，多副本，无状态)
                            |
        ┌───────────────────┼───────────────────┐
        │                   │                   │
  Agent Runtime        PostgreSQL         Redis
  (LangGraph 副本)     (主从 + 备份)      (集群)
        │                   │                   │
  Docker 沙箱池          Milvus           对象存储
  (动态创建销毁)         (托管/集群)      (MinIO/OSS/S3)
```

## 2. 环境规划

| 环境 | 用途 | 规模 |
| --- | --- | --- |
| Local | 本地开发 | Docker Compose 单机 |
| Staging | 测试/预发 | 单副本，近似生产 |
| Production | 生产 | 多副本，高可用 |

## 3. 本地开发环境（Docker Compose）

```yaml
services:
  frontend:    # Next.js
    build: ./frontend
    ports: ["3000:3000"]
  backend:     # FastAPI
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [database, cache, vector]
  agent:       # LangGraph Runtime
    build: ./agent
    depends_on: [backend, sandbox]
  database:    # PostgreSQL
    image: postgres:16
    volumes: ["pg_data:/var/lib/postgresql/data"]
  vector:      # Milvus
    image: milvusdb/milvus
  cache:       # Redis
    image: redis:7
  minio:       # 对象存储（S3 兼容）
    image: minio/minio
```

一键启动：`docker compose up -d`。

## 4. 生产环境部署（Kubernetes）

### 4.1 组件部署方式

| 组件 | 部署方式 | 扩缩容 |
| --- | --- | --- |
| 前端 Next.js | Deployment + Ingress | HPA（CPU/请求） |
| FastAPI | Deployment（无状态） | HPA |
| Agent Runtime | Deployment（无状态） | HPA（任务队列深度） |
| PostgreSQL | 云托管 RDS 或 StatefulSet | 主从 |
| Redis | 云托管或 StatefulSet | 集群 |
| Milvus | 云托管或 Operator | 按需 |
| 对象存储 | 云 OSS/S3 托管 | 托管 |

### 4.2 沙箱池管理（重点）

沙箱是 DevPilot 最特殊的运维对象，采用**动态创建销毁**策略：

- 每个任务启动时创建独立沙箱容器，任务结束立即销毁
- 预热池：预创建空闲沙箱，降低冷启动延迟（目标 < 5s）
- 沙箱运行在**独立节点池**（gVisor/Firecracker 隔离），与业务服务物理隔离
- 资源限额：CPU / 内存 / 磁盘 / 网络 / 执行超时，超限即终止
- 沙箱镜像分层：基础工具镜像 + 任务类型专用镜像

## 5. CI/CD 流水线

```text
Push → 单元测试 → 集成测试 → 沙箱安全测试 → 构建镜像 → 部署 Staging
     → E2E + 性能 + 成本回归 → 部署 Production（灰度）
```

- 镜像构建：多阶段 Dockerfile，前端/后端/Agent 独立镜像
- 灰度发布：先 10% 流量 → 观察指标 → 全量
- 回滚：镜像版本回滚，秒级

## 6. 监控与告警

### 6.1 监控指标

| 类别 | 指标 |
| --- | --- |
| 应用 | 请求量、错误率、P95 延迟、SSE 首字节 |
| Agent | 任务成功率、单任务耗时、token 消耗、迭代次数分布 |
| 沙箱 | 池大小、冷启动延迟、逃逸尝试次数、资源超限次数 |
| 基础设施 | CPU/内存/磁盘/网络、数据库连接数、队列深度 |
| 成本 | 按模型/任务的 token 与费用、单任务成本 |

### 6.2 技术栈

- 指标：Prometheus + Grafana
- 日志：ELK 或 Loki（结构化日志）
- Trace：OpenTelemetry + Jaeger
- 告警：Alertmanager → 企业微信/邮件

### 6.3 关键告警

| 告警 | 阈值 | 级别 |
| --- | --- | --- |
| 沙箱逃逸尝试 | > 0 | P0（立即） |
| 单任务成本突增 | > 基线 20% | P1 |
| 任务成功率骤降 | < 60% | P1 |
| API 错误率 | > 1% | P1 |
| 沙箱池耗尽 | 空置 < 10% | P2 |

## 7. 日志规范

- 结构化 JSON 日志，字段统一（trace_id、task_id、user_id、agent_name）
- 全链路 trace_id 贯穿（前端→API→Agent→工具）
- 敏感信息脱敏（token、密码、密钥）

## 8. 备份与恢复

| 对象 | 策略 | RPO | RTO |
| --- | --- | --- | --- |
| PostgreSQL | 每日全量 + 实时 WAL 归档 | < 5min | < 30min |
| 对象存储 | 跨区副本 / 版本控制 | 实时 | < 1h |
| Milvus | 定期快照 + 重建 | < 24h | < 4h |
| Redis | 持久化（AOF），短期记忆可重建 | 可重建 | — |

## 9. 安全运维

- 定期沙箱渗透测试（每月）
- 镜像安全扫描（Trivy/Clair）
- 依赖漏洞扫描（Snyk/Dependabot）
- 密钥管理（Vault / 云 KMS），不落盘
- 最小权限原则（服务账号、网络策略、RBAC）
- 审计日志保留与合规

## 10. 容量规划

| 阶段 | 用户规模 | 资源估算 |
| --- | --- | --- |
| MVP | < 1000 注册，< 100 并发 | 单节点即可 |
| 增长期 | 万级注册 | 服务多副本 + 沙箱独立节点池 |
| 规模化 | 十万级 | 全组件高可用 + 多可用区 |

关键扩容信号：沙箱池利用率、任务队列深度、token 消耗增长曲线。
