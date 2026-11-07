import type { ReportForm } from "./form";

type Messages = {
  title: string;
  notice: string;
  template: string;
  loading: string;
  empty: string;
  retry: string;
  metadata: string;
  effect: string;
  performance: string;
  narrative: string;
  mode: string;
  baseline: string;
  acceptance: string;
  population: string;
  tokenSource: string;
  streaming: string;
  generate: string;
  generating: string;
  invalid: string;
  help: string;
  preview: string;
  downloadMd: string;
  downloadJson: string;
  labels: Record<Extract<keyof ReportForm, string>, string>;
};

export const enReports: Messages = {
  title: "Report workspace",
  notice:
    "DRAFT: manually entered, unverified results. This is not an acceptance decision. Do not enter secrets or unnecessary personal data. This preview is not saved on the server; download it before leaving. Template editing, formal approval and historical revisions are not available yet.",
  template: "Template version",
  loading: "Loading templates…",
  empty: "No published templates are available.",
  retry: "Reload templates",
  metadata: "Report information",
  effect: "Include effect results",
  performance: "Include performance results",
  narrative: "Scope, evidence and limitations",
  mode: "Evaluation mode",
  baseline: "Baseline (exploratory)",
  acceptance: "Acceptance (draft only)",
  population: "Latency population",
  tokenSource: "Token source",
  streaming: "Content streaming was enabled",
  generate: "Generate draft",
  generating: "Generating…",
  invalid:
    "Check required fields and integer counts. All effect outcomes must sum to the total; at least one results section is required.",
  help: "Effect pass rate = passed / total (including pending and unexecuted cases). Blank performance measurements stay unavailable, not zero. For latency, enter the matching sample count and population. TTFT requires content streaming and a successful-request sample count. TPS means aggregate output tokens per second; declare how tokens were counted. Explain measurement scope and missing evidence below.",
  preview: "Draft preview",
  downloadMd: "Download Markdown",
  downloadJson: "Download JSON",
  labels: {
    title: "Report title",
    project_name: "Project",
    component_name: "Component",
    component_version: "Component version",
    tester: "Reported tester",
    test_period: "Reported test period",
    environment: "Test environment",
    scope: "Test scope",
    methodology: "Methodology and statistical definitions",
    evidence_notes: "Evidence references (unverified)",
    limitations: "Limitations and unresolved questions",
    total: "Total cases",
    passed: "Passed",
    failed: "Failed",
    errors: "Errors",
    pending: "Pending review",
    not_run: "Not executed",
    requests: "Total requests",
    successful_requests: "Successful requests",
    concurrency: "Concurrency",
    latency_mean_ms: "Mean latency (ms)",
    latency_sample_count: "Latency sample count",
    ttft_mean_ms: "Mean TTFT (ms)",
    ttft_sample_count: "TTFT sample count",
    throughput_tokens_per_s: "Aggregate output throughput (tokens/s)",
    evaluation_mode: "Evaluation mode",
    includeEffect: "Effect results",
    includePerformance: "Performance results",
    content_streaming: "Content streaming",
    metric_population: "Latency population",
    token_source: "Token source",
  },
};

export const zhReports: Messages = {
  title: "评测报告工作台",
  notice:
    "草稿：人工填报、结果未经核验，不构成验收结论。请勿填写凭据或不必要的个人信息。本页不会在服务端保存报告，离开前请下载。模板编辑、正式审批与历史修订尚未开放。",
  template: "模板及版本",
  loading: "正在加载模板…",
  empty: "暂无可用的已发布模板。",
  retry: "重新加载模板",
  metadata: "报告信息",
  effect: "包含效果测试结果",
  performance: "包含性能测试结果",
  narrative: "范围、证据与限制",
  mode: "评测模式",
  baseline: "摸底评测",
  acceptance: "验收评测（仅草稿）",
  population: "延迟统计范围",
  tokenSource: "Token 统计来源",
  streaming: "测试时启用了内容流式",
  generate: "生成草稿",
  generating: "正在生成…",
  invalid:
    "请检查必填项及整数计数。各类效果结果数量之和必须等于总数，且至少填写一类测试结果。",
  help: "效果通过率 = 通过数 / 总数（含待审和未执行）。性能指标留空表示未测量，而不是零；填写延迟需明确统计范围与对应样本数。TTFT 仅适用于内容流式，并需填写成功请求中的有效样本数。TPS 表示整体输出 tokens/s，需注明计数来源。请在下方说明测量口径、统计时间窗与缺失证据。",
  preview: "草稿预览",
  downloadMd: "下载 Markdown",
  downloadJson: "下载 JSON",
  labels: {
    title: "报告标题",
    project_name: "项目名称",
    component_name: "组件名称",
    component_version: "组件版本",
    tester: "测试人员（自述）",
    test_period: "测试时间范围（自述）",
    environment: "测试环境",
    scope: "测试范围",
    methodology: "测试方法与统计口径",
    evidence_notes: "证据引用（未核验）",
    limitations: "限制与待确认事项",
    total: "总样本数",
    passed: "通过数",
    failed: "不通过数",
    errors: "错误数",
    pending: "待复核数",
    not_run: "未执行数",
    requests: "请求总数",
    successful_requests: "成功请求数",
    concurrency: "并发数",
    latency_mean_ms: "平均响应时间（ms）",
    latency_sample_count: "延迟样本数",
    ttft_mean_ms: "平均 TTFT（ms）",
    ttft_sample_count: "TTFT 样本数",
    throughput_tokens_per_s: "整体输出吞吐（tokens/s）",
    evaluation_mode: "评测模式",
    includeEffect: "效果结果",
    includePerformance: "性能结果",
    content_streaming: "内容流式",
    metric_population: "延迟统计范围",
    token_source: "Token 来源",
  },
};
