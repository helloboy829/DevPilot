export interface ReportTemplateSummary {
  id: string;
  version: string;
  language: string;
  name: string;
  schema_version: string;
}

export interface EffectResults {
  total: number;
  passed: number;
  failed: number;
  errors: number;
  pending: number;
  not_run: number;
}

export interface PerformanceResults {
  requests: number;
  successful_requests: number;
  concurrency: number;
  metric_population: "successful_requests" | "all_attempts" | "failed_attempts";
  latency_mean_ms: number | null;
  latency_sample_count: number;
  content_streaming: boolean;
  ttft_mean_ms: number | null;
  ttft_sample_count: number;
  throughput_tokens_per_s: number | null;
  token_source: "unavailable" | "provider_usage" | "tokenizer" | "estimate";
}

export const metadataFields = [
  "title",
  "project_name",
  "component_name",
  "component_version",
  "tester",
  "test_period",
] as const;
export const narrativeFields = [
  "environment",
  "scope",
  "methodology",
  "evidence_notes",
  "limitations",
] as const;
export const effectFields = [
  "total",
  "passed",
  "failed",
  "errors",
  "pending",
  "not_run",
] as const;
export const performanceCountFields = [
  "requests",
  "successful_requests",
  "concurrency",
] as const;
export const measurementFields = [
  "latency_mean_ms",
  "ttft_mean_ms",
  "throughput_tokens_per_s",
] as const;
export const sampleFields = [
  "latency_sample_count",
  "ttft_sample_count",
] as const;
export type TextField =
  | (typeof metadataFields)[number]
  | (typeof narrativeFields)[number];
export type NumericField =
  | (typeof effectFields)[number]
  | (typeof performanceCountFields)[number]
  | (typeof measurementFields)[number]
  | (typeof sampleFields)[number];

export type ReportFacts = Record<TextField, string> & {
  evaluation_mode: "BASELINE" | "ACCEPTANCE";
  effect: EffectResults | null;
  performance: PerformanceResults | null;
};

export interface ReportPreview {
  status: "DRAFT";
  source: "manual_unverified";
  facts: ReportFacts;
  template: ReportTemplateSummary & Record<string, unknown>;
  derived: { case_pass_rate: number | null; success_rate: number | null };
  manifest: {
    schema_version: string;
    renderer_version: string;
    template_id: string;
    template_version: string;
    facts_sha256: string;
    template_sha256: string;
    generated_by: string;
    generated_at: string;
  };
  markdown: string;
}
