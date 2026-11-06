export type ComponentTestTransport =
  | "openai_chat"
  | "dify_chat"
  | "dify_workflow"
  | "http_post";

export type ComponentResponseMode = "blocking" | "streaming";

export type ComponentValidationType =
  | "reference_text"
  | "manual_review"
  | "reference_values"
  | "field_completeness"
  | "structure";

export type AcceptanceCriteria = {
  effect?: {
    accuracy_min?: number;
    completeness_min?: number;
    structure_min?: number;
    overall_min?: number;
  };
  perf?: {
    success_rate_min?: number;
    p95_latency_max_ms?: number;
    ttft_p95_max_ms?: number;
    min_qps?: number;
    min_throughput_tok_per_s?: number;
  };
};

export type Component = {
  id: string;
  user_id: string;
  name: string;
  component_code: string | null;
  transport: string;
  api_url: string;
  api_token: string | null;
  response_mode: string;
  supports_streaming: boolean;
  validation_type: string;
  acceptance_criteria: AcceptanceCriteria;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type ComponentTestRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "aborted";

export type ComponentTestType = "effect" | "perf";

export type EffectSampleResult = {
  sample_index: number;
  validation_type: string;
  status: "passed" | "failed" | "manual_review" | "error" | "not_run";
  judge: {
    accuracy: number;
    completeness: number;
    structure: number;
    overall: number;
    report: string;
  } | null;
  reference_text: string | null;
  output_text: string | null;
  error: string | null;
};

export type EffectReport = {
  total: number;
  passed: number;
  failed: number;
  manual_review: number;
  error: number;
  // Optional only for compatibility with stored legacy reports.
  not_run?: number;
  pass_rate?: number;
  auto_total: number;
  auto_pass_rate: number;
  overall: "PASS" | "FAIL" | "REVIEW";
  summary: Record<string, unknown>;
  samples: EffectSampleResult[];
};

export type PerfLevelResult = {
  concurrency: number;
  total: number;
  success: number;
  failed: number;
  success_rate: number;
  wall_time_ms: number;
  success_qps: number;
  throughput_tok_per_s: number;
  total_tokens: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  latency_p99_ms: number | null;
  ttft_p50_ms: number | null;
  ttft_p95_ms: number | null;
  latency_sample_count?: number;
  ttft_sample_count?: number;
};

export type PerfReport = {
  overall: "PASS" | "FAIL";
  summary: PerfLevelResult | null;
  checks: Record<string, boolean>;
  check_reasons?: Record<string, string>;
  levels: PerfLevelResult[];
};

export type RunResultSummary = {
  assessment_version?: string;
  overall: "PASS" | "FAIL" | "REVIEW";
  component_name: string;
  test_type: ComponentTestType;
  effect?: {
    total?: number;
    pass_rate?: number;
    error?: number;
    not_run?: number;
    passed: number;
    failed: number;
    manual_review: number;
    auto_pass_rate: number;
    overall: string;
  };
  perf?: {
    checks?: Record<string, boolean>;
    check_reasons?: Record<string, string>;
    overall: string;
    concurrency: number | null;
    success_rate: number | null;
    success_qps: number | null;
    throughput_tok_per_s: number | null;
    p95_latency_ms: number | null;
    ttft_p95_ms: number | null;
  };
};

export type ComponentTestRun = {
  id: string;
  user_id: string;
  component_id: string;
  test_type: ComponentTestType;
  status: ComponentTestRunStatus;
  params: Record<string, unknown>;
  result: RunResultSummary | null;
  raw_path: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type ComponentTestReport = {
  assessment_version?: string;
  component: {
    id: string;
    name: string;
    transport: string;
    validation_type: string;
  };
  test_type: ComponentTestType;
  params: Record<string, unknown>;
  effect?: EffectReport;
  perf?: PerfReport;
};
