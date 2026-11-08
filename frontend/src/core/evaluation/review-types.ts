import type { EffectivenessCriteria } from "./plan-types";

export type ReviewDecision = "pass" | "fail" | "uncertain";
export interface ReviewRun {
  id: string;
  component_name: string;
  plan_label: string;
  status: string;
  request_count: number;
}
export interface ReviewCaseMetadata {
  ordinal: number;
  sample_id: string;
  state: string;
  kind: string | null;
  has_output_evidence: boolean;
  review_revision: number;
  review_decision: ReviewDecision | null;
}
export interface ReviewCasePage {
  scope: "human_review_only";
  run: ReviewRun;
  cases: ReviewCaseMetadata[];
  counts: Record<ReviewDecision | "unreviewed", number>;
  offset: number;
  limit: number;
}
export interface ReviewCase {
  scope: "human_review_only";
  run_id: string;
  ordinal: number;
  sample_id: string;
  component_name: string;
  plan_label: string;
  state: string;
  input: string;
  expected: string;
  output: string | null;
  source_ref: string;
  slice_tag: string;
  evidence_hash: string | null;
  case_hash: string;
  technical: {
    kind: string | null;
    http_status: number | null;
    body_bytes: number | null;
    elapsed_ms: number | null;
  };
  review_revision: number;
  reviews: {
    revision: number;
    decision: ReviewDecision;
    reviewer_id: string;
    note: string;
    created_at_ms: number;
  }[];
}

export interface CriteriaEvaluation {
  scope: "effectiveness_threshold_only";
  criteria: EffectivenessCriteria;
  status: "met" | "not_met" | "incomplete";
  blockers: string[];
  approval: "not_approved";
}

export interface ReviewSummary {
  criteria_evaluation?: CriteriaEvaluation;
  schema: "qa-human-summary.v1";
  scope: "verified_human_summary_preview";
  run_id: string;
  run_status: string;
  project_id: string;
  component_id: string;
  component_name: string;
  plan_id: string;
  plan_label: string;
  plan_hash: string;
  summary_hash: string;
  counts: Record<ReviewDecision | "unreviewed", number>;
  technical_counts: { collected: number; other: number };
  human_pass_rate: { numerator: number; denominator: number; value: number };
  readiness: "provisional" | "review_complete";
  blockers: (
    | "collection_not_finished"
    | "technical_incomplete"
    | "unreviewed"
    | "uncertain"
  )[];
  acceptance: "not_approved";
}
