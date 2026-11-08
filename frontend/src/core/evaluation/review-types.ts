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
