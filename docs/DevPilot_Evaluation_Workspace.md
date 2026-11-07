# DevPilot 评测工作台增量交付与配置

## 2026-11-08：稳定导航与五套视觉风格

固定评测/协作菜单，新建对话移回页面；五种风格独立搭配明暗模式，偏好仅当前浏览器保存。修复上一提交前端 AGENTS Markdown 未格式化导致的真实 CI 失败，不绕过门禁。[设计、限制和验证](DevPilot_Workspace_Styles_CI.md)。这不替代后续持久执行、人工复核与报告证据主线。

## 2026-11-07 追加切片：助手默认开放 / 请求模板

所有已登录用户默认可管理自己的助手；个人 USER.md 按账号隔离，管理员可主动关闭。cURL 调试器可导出带结构指纹的参数化 JSON，请求值均为运行时引用。此切片不保存服务端请求版本、不查找凭据、不发送请求，也不是可执行脚本或评测证据。[交付与剩余边界](DevPilot_Assistants_Request_Templates.md)。


## 项目 / QA 数据增量（2026-11-07）

导航新增 /workspace/datasets：本人项目、来源与授权声明、JSON/JSONL草稿全量导入、Q/金标/来源同屏检查、显式确认冻结与操作记录。专用 evaluation_projects:read/write/review 权限，共用持久库但独立 App Alembic版本表；未启用持久库503。当前本人自审、不调用模型、不访问来源，不等于正式双人审核或验收通过；尚未与现有组件、运行和报告建立版本关联。详见[QA最小闭环](DevPilot_QA数据最小闭环.md)。

日期：2026-11-07。本文是当前代码状态补充；早期可行性、技术方案中的路线图仍是目标设计，不能据此声称整条评测闭环已完成。

## 1. 分层与产品收敛

产品名称为 DevPilot，用户可见标题、登录/初始化、导航和中英文内容统一；底层 `deerflow` 导入、协议 key、既有存储、环境变量以及 ByteDance 上游归属保留。通用功能不做无依赖分析的大规模物理删除。左侧原定时入口改为定时评测；旧聊天调度 API/页面仅兼容保留，不作为评测产品主入口。

- `devpilot.http`、`devpilot.reporting.project`：纯逻辑，不依赖 App/Harness。
- `app.evaluation`：出站策略、冻结计划、确定性调度。
- `app.reporting.intake`：报告多轮字段建议，无工具/记忆/持久会话；前文由客户端携带，不是可信证据。
- `deerflow.config.managed_models`：不依赖 App 的可选加密模型配置覆盖层。
- Gateway：认证/权限/授权、边界限制；前端始终通过现有认证/CSRF fetcher。

默认 /workspace 进入 /workspace/evaluations。主导航围绕组件、定时评测、报告与模型连接；渠道与最近会话只在聊天/Agents 路由显示。首页库存来自本人组件接口，失败显示未知，不能把登记数称为通过数。

## 2. 新 API 与权限

| API | 权限与效果 |
| --- | --- |
| `POST /api/component-tests/debug/parse` | threads:write；仅解析、不执行 |
| `POST /api/component-tests/debug/send` | threads:write + runs:create + consent；单次受控出站 |
| `GET/POST /api/evaluation-schedules` | 读取本人计划；创建需写/运行权限及 consent |
| `GET /api/reports/project/templates` | threads:read；固定版本目录 |
| `POST /api/reports/project/preview` | threads:write；人工多组件草稿 |
| `POST /api/reports/project/intake` | threads:write + runs:create + consent；需求文本发送给明确配置的模型 |
| `/api/model-management` | 管理员；GET 目录，PUT models/roles，DELETE 指定模型，POST 指定模型 probe |

敏感新路由验证失败不回显提交值；响应禁止缓存。模型变更使用 revision 防止覆盖并发编辑。模型协议白名单扩展到 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages、Gemini Developer API；保持旧 openai_compatible ID 兼容。服务商标签、地址和模型 ID 自定义；不接受任意 Python import、SDK kwargs 或认证头。YAML 模型不能从页面覆盖，同名冲突拒绝加载。

## 3. 运行配置

实际配置和密钥不能提交。可选示意：

```yaml
scheduler:
  enabled: true

evaluation_http:
  allowed_hosts: [] # 管理员填入已获准的精确目标主机名，不含 scheme/path
  allow_private: false # 只有明确批准内部目标时才放开私网
```

空白名单默认拒绝调试、手动效果/性能和定时评测出站。TLS 校验保持开启，不支持用户通过 cURL `-k` 绕过；内部自签证书应通过管理员信任的 CA 链部署。禁用代理环境与重定向，检查 DNS 返回地址并固定实际连接 IP，保留原 Host/SNI。

模型目录通过 Gateway 环境变量设置：

```text
DEVPILOT_MODEL_CATALOG_DIR=/data/model-catalog
DEVPILOT_MODEL_ENCRYPTION_KEY=<由密钥管理注入的 Fernet key；不要写进文档或提交>
```

后一项可省略，自动生成目录下的 `catalog.key`。目录必须私有且持久化；丢失密钥无法解密。生产应分离管理和备份密钥，不把同卷加密等同于独立密钥托管；Windows 上需显式收紧 ACL。模型目录未设置时页面明确返回不可用，不能默默写临时数据库。

报告模型可通过页面绑定 `report_advisor`，也可继续由管理员用 `config.yaml -> reports_agent` 配置命名模型。移除页面绑定时恢复 operator 配置，不保证关闭 operator 已启用的助手。默认 Agent 与报告角色已接通，其余角色仅预留绑定。

### 连接档案与切换

模型页提供协议预设、连接搜索/新增/编辑/复制、默认切换与角色路由。复制不携带密钥；修改已有档案的 endpoint/protocol 时必须重新输入或明确清除旧密钥。留空只在地址和协议不变时保留旧值。每次修改携带 revision，冲突先重载，不静默覆盖。

受控参数：temperature 0..2、top_p (0,1]、max_tokens 1..65536、timeout_seconds 1..300、max_retries 0..2。上游模型可能有更严格限制，需单独验证。Responses 显式 store=false；Gemini 固定 API-key Developer API（vertexai=false）。连接档案并非共享服务商密钥实体；不支持 OAuth、任意 JSON 导入、自动 failover 或全 CC Switch 客户端切换。

## 4. 定时评测语义

计划保存组件非凭据配置哈希、数据与负载参数、时间/时区，运行时读取本人组件凭据。凭据轮换不要求复制计划；URL、协议、响应模式和标准变更会使旧计划拒绝执行。启动重新检查用户和运行权限。性能每档请求数、并发、档数、单次超时均受限；不接受自由 prompt、delivery 或用户指定 headers/judge。

调度器的租约、历史、防重叠和重启中断记录复用原实现；执行最终状态回填调度记录。组件执行任务仍在进程内，不代表已经有分布式耐久评测 Worker。任务取消会终结组件记录并关闭传入 client；暂停仅影响未来运行。单次终结计划需重新确认，不应恢复成新的自动重跑；通用调度 API 也禁止手动重放评测计划，以免绕过已经确认的运行时段。需要立即运行时，应重新明确授权组件测试。

**效果计划目前只做返回采集并标记人工待审**：授权调用被测组件不等于授权向外部裁判模型外发答案。后续接入显式命名裁判、数据外发许可、独立预算和版本化 rubric。不得宣传当前已自动评分所有定时效果任务。

## 5. 报告与 Agent 的责任边界

项目报告包含多个独立组件快照，仍复用原组件事实校验。共享项目、测试人、周期、模式必须一致；不同组件不做简单平均，不能把人工输入标成平台已核验。模板继承参考材料中通用的目的/范围/依据/环境/对象/指标/效果/性能/结论/附录结构；没有复制客户内容、历史数值或 DOCX 版式。

两个可选 Agent 路径：

1. 需求整理：可见多轮对话，用户主动填写的短文本；可含主动输入的名称，页面明确提醒，不自动附带现有指标/本地文件。返回严格字段建议和问题；确认后只填写基础字段，不修改测量值。多个组件建议先列出，当前确认自动填首组件，其余逐个填报。
2. 指标解释：旧助手只接收白名单汇总 DTO，不发名称/自由文本/原始证据。解释也是待人工确认的非事实附录。

两者无工具、记忆、checkpointer/store、tracing，限制超时/输出/并发，无自动重试，不回显 provider 原始错误。模型服务商的日志留存仍由运营者政策控制。多轮上限为 10 轮（history 最多 9 个已完成往返），当前消息不超过 4000 字符，序列化上下文不超过 24000 字符。每轮重新同意发送本轮及前文；使用严格 message/proposal DTO，不接受任意 role/system 消息。仅当前页面内存、离开不恢复，非服务端持久会话，也没有正式报告审批权限。

## 6. 当前限制与下一步

详见[实现矩阵与下一步](DevPilot_实现进度与下一步.md)，按代码证据区分已完成切片、原型和未实现领域，不能以导航存在宣布里程碑完成。

- 调试支持常用 HTTP/JSON，不支持完整 Postman，也未统一到所有旧评测适配器或导出脚本。
- 调试、手动与定时组件调用已统一出站传输，详见[导航与统一出站基线](DevPilot_导航与统一出站基线.md)。完整 RequestSpec/body、凭据引用、耐久任务/配额和证据链仍待实现；不能宣称全平台安全工作完成。
- 项目报告是无服务端持久化的 DRAFT，模板版本固定但无上传/编辑/历史修订台；仅 Markdown/JSON，无 DOCX/PDF。
- 原生 TTFT 只在适用的流式内容增量中有意义；缺测和不适用不得填零。
- 优先建设数据治理与冻结，再完善复核中心、证据回链、耐久执行、正式模板生命周期和经审核知识闭环。

## 7. 验收原则

新增测试只用合成组件、合成名称/数值和 mock 接口/模型。检查管理员权限、密钥不回显、revision 冲突、显式同意、固定分母、计划变更拒绝、取消终结、多个组件快照和字段确认。生产模型/业务接口兼容性须后续在批准环境单独验收。

本地原材料、真实报告、配置、模型库、数据库和运行日志均不入 Git。发布前同时检查未跟踪文件和待推送提交，不只是检查工作区 diff。
