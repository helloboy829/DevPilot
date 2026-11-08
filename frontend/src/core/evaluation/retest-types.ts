import type { ReviewCase, ReviewSummary } from "./review-types";

export type RetestTransition =
  | "fail_to_pass"
  | "pass_to_fail"
  | "pass_to_pass"
  | "fail_to_fail";
export interface RetestSource {
  run_id: string;
  summary_hash: string;
}
export interface PendingRetest {
  id: string;
  baseline: RetestSource;
  retest: RetestSource;
}
export interface RetestCase {
  ordinal: number;
  sample_id: string;
  transition: RetestTransition;
  baseline_decision: "pass" | "fail";
  retest_decision: "pass" | "fail";
  baseline_case_hash: string;
  retest_case_hash: string;
  baseline_revision: number;
  retest_revision: number;
  baseline_review_hash: string;
  retest_review_hash: string;
}
export interface RetestArchive {
  schema: "qa-retest-archive.v1";
  scope: "same_benchmark_human_comparison";
  id: string;
  project_id: string;
  project_name: string;
  component_id: string;
  component_name: string;
  created_at_ms: number;
  baseline: ReviewSummary;
  retest: ReviewSummary;
  benchmark: Record<string, unknown>;
  benchmark_hash: string;
  request_definition_changed: boolean;
  transitions: Record<RetestTransition, number>;
  cases: RetestCase[];
  pass_rate_delta: { numerator: number; denominator: number; value: number };
  acceptance: "not_approved";
  archive_hash: string;
}
export interface RetestMetadata {
  id: string;
  baseline_label: string;
  retest_label: string;
  baseline_run_id: string;
  retest_run_id: string;
  created_at_ms: number;
}
export interface RetestEvidence {
  baseline: ReviewCase;
  retest: ReviewCase;
  frozen: RetestCase;
}
