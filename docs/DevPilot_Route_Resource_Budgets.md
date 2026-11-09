# 路由资源预算与加载边界 / Route resource budgets and loading boundaries

> 2026-11-10：前端候选模块；不部署、不改预算、不调用真实模型/目标。此文与本机 ignored 证据区分源码、测量、实际 Actions 和运行验收。

## 问题与范围

上一模块 `833897a367ea8ef0a1a030f4e1e93dc098caec11` 的五项实际 Actions 已 completed/success：E2E `42678402551`、Frontend Unit Tests `42678402624`、Lint Check `42678402195`、Replay E2E `42678402254`、Unit Tests `42678402516`。未触发的 Backend Blocking IO / Skill Review 不记为通过。该提交的本地 `pnpm perf:check` **失败**；Actions 没有运行此性能 gate，不能用绿色徽章抹去失败。

本模块修复同一锁文件/Node 22 环境中的真实入口资源，不改 `performance-budgets.json`、六条基准路由、资产提取或计量方式。指标为现有脚本计算的入口 JS/CSS 原始字节，不是 gzip、Lighthouse、交互延迟或全部懒加载资产总和。`/login` 使用正常构建，其余路由沿用既有 static-demo 构建；不能冒充登录后真实业务验收。

## 根因与实现合同

### 1. 文档导航只加载内容，不加载工作台运行模块

锁文件中的 Nextra 4.6.1 生成器扫描 App `page.tsx`，在 page-map 中发出整个页面的 namespace import，再交给 `getMetadata`。现有 docs/blog 消费方稍后才筛选内容；工作台 client references 已先注册进文档入口。

- `content-page-map-loader.cjs` 通过已有 TypeScript AST，只将 `private-next-root-dir/(src/)app/**/page.[jt]sx?` 的 namespace import 改为空 metadata 对象。保留 map 拓扑、内容 MDX metadata、`_meta` import、RouteToFilepath 和后续现有中英文/博客过滤。
- 不替换真实 App 页面、handler、权限、认证、响应或用户内容；该 loader 仅运行于构建期的 Nextra page-map placeholder。
- 缺少生成器标记、解析失败、不支持的 App import/re-export/dynamic import、路径穿越或 query 均以通用错误阻止构建，不静默漏掉未知上游形态。
- `content-page-map-config.mjs` 精确匹配唯一 placeholder，保留 Nextra/其他 loader/alias/output/webpack hook。Turbopack 逆序运行，projection 排在 Nextra 后；Webpack 使用 exact-placeholder post-loader。升级 Nextra 必须复核生成器合同和两种实际构建，不是通用 tree-shaking 开关。

### 2. 完整动态 HTML 样式属于对应的懒加载预览

- `globals.css` 使用 `source(none)` 与显式 runtime `src`、public demo、完整 Streamdown/code/mermaid chunks；不扫描测试、构建产物。完整 Streamdown glob 保留拆分 chunk 中的流式渲染样式，而不是只扫描 index。
- 原有 **所有** `@source inline` 动态 HTML 调色板原样保留于 `rich-html.css`；冻结 JSON 夹具逐项断言，不能为了预算删颜色/间距/排版能力。
- `theme-tokens.css` 提取原有完整 inline theme，不带 source/preflight。动态 palette 仅引用它与 Tailwind theme，不引用带全应用 sources 的 globals，避免重复生成整个应用 utilities。
- Markdown artifact 使用进一步 lazy 的 `artifact-markdown-preview.tsx`，仍沿用 SafeStreamdown、原 plugins、ArtifactLink 和 CitationSourcesPanel。只有真正打开 Markdown 预览才加载 palette；HTML iframe、编辑器及普通聊天不无条件加载它。已 lazy 的 memory settings 也显式拥有 palette。raw HTML 解析/清洗合同没有扩大。

没有新依赖、lockfile、后端运行行为、迁移、私有配置或功能开关变更。候选迁移仍 `eval_0012`；历史部署 `eval_0009` 不因此改变。

## 同口径性能结果

| 路由                                                    | 原 CSS | 本模块 CSS |   原 JS | 本模块 JS |  CSS / JS 原预算 |
| ------------------------------------------------------- | -----: | ---------: | ------: | --------: | ---------------: |
| `/login`                                                | 177416 |     164719 |  837927 |    837927 |  170000 / 850000 |
| `/`                                                     | 177416 |     164719 |  859845 |    859731 | 175000 / 1050000 |
| `/workspace/chats`                                      | 202088 |     189391 | 1687992 |   1687965 | 190000 / 1750000 |
| `/workspace/chats/7cfa5f8f-a2f8-47ad-acbd-da7137baf990` | 202088 |     189391 | 4026811 |   4015547 | 190000 / 4100000 |
| `/en/docs`                                              | 280386 |     267689 | 4436096 |   1013381 | 270000 / 4200000 |
| `/blog/posts`                                           | 280386 |     267689 | 4436096 |   1013381 | 270000 / 4200000 |

最终 `pnpm perf:check` exit 0，所有原预算通过。聊天入口 CSS 只有 **609 bytes** 余量，仍需持续测量；这不是无限性能余量，也不说明 lazy Markdown 的完整 palette 被删除。

## 失败记录与回归

- 包级 `optimizePackageImports` 实验没有改善字节数，已撤销，保留失败日志/measurements，不带入交付。
- 第一版 projection 已降低文档 JS，但 rich CSS 引用 globals 且 viewer 无条件导入 palette，thread CSS 达 **360187 bytes**，预算仍失败。修正为无 source 的 theme tokens 与 Markdown 专属 lazy 边界，不抬预算、不删路由。
- 新样式测试最初把注释里的 `tests/build` 当成 source；改为精确断言完整 `@source` 指令清单，仍禁止非 runtime 扫描。测试编写阶段 ESM loader URL/语法问题保留，不放宽运行合同。
- 新增 loader/config **28 项**、真实 PostCSS/Tailwind 编译与历史 palette/source ownership **3 项**；完整 frontend **152 files / 1293 passed**。原有 Markdown/代码/数学/引用/中英文文档与 auth/工作台浏览器用例保留；新增 raw HTML palette 实际浏览器回归。
- 完整 Prettier（包含 Markdown）、ESLint、typecheck、Webpack 与 Turbopack 实际生产构建通过。完整模拟 Chromium **231 passed / 2.5m**、独立认证恢复 **2 passed / 1.2m**，均明确 `retries=0`。新增浏览器用例实际验证 lazy palette 的间距/字体/行高/颜色 token，现有 docs 中英文导航与工作台入口均保留。本模块不改后端，不把上一轮后端全量当成本轮重跑。

证据目录 `.deer-flow/ci/20261110-route-resource-budgets/` ignored；不得提交本地日志、配置、浏览器身份或数据库。完成所有进程、导出与 archive/member hash 核对后，仅停止本模块启动的精确 CI 容器，保留依赖缓存、业务服务、镜像和卷；无 prune、force 或部署。

## 回退与边界

回退本模块的 build wrapper/loader、CSS ownership 与 artifact child 拆分即可；不编辑历史迁移/档案/hash，不关闭预算或删回归。两种生产构建和 docs/blog/工作区路由必须一并复核。安全 Lost Worker fencing/释放、冻结 QA 调度准入、统一可执行导出、正式批准政策和另行授权的保留数据升级/真实用户验收仍未完成。

## English summary

This frontend-only candidate fixes actual entry assets under the unchanged six-route budget script. A narrowly guarded build-time AST post-loader prevents Nextra's content navigation map from importing unrelated App page runtimes, while preserving content MDX metadata, map topology and existing docs/blog filtering. Unknown generator shapes fail closed. Turbopack and Webpack have separate exact-placeholder wiring; App routes themselves are never rewritten. Every historical dynamic raw-HTML utility is retained in a lazy palette with source-free shared theme tokens; runtime source scanning includes complete Streamdown plugin chunks but excludes tests/build artifacts. Only Markdown artifact previews and lazy memory settings own the palette, not iframe/editor entry paths. All original asset budgets now pass; chat CSS has just 609 bytes of headroom. Failed import-optimization and duplicated-CSS experiments are retained honestly. There is no new dependency, migration, backend behavior, configuration change, deployment, real call or approval authority. The remaining platform and real-user acceptance gaps are not closed by a performance pass.
