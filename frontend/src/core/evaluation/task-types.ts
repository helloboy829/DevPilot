import type { ReviewCase, ReviewDecision } from "./review-types";

export type TaskRole = "reviewer_1" | "reviewer_2" | "arbitrator";
export type TaskStatus =
  | "queued"
  | "in_review"
  | "escalated"
  | "resolved"
  | "cancelled";
export interface TaskAssignment {
  role: TaskRole;
  status: "offered" | "active" | "expired" | "released" | "submitted";
  lease_until_ms: number | null;
  actor_id?: string;
}
export interface ReviewTask {
  scope: "independent_review_only";
  policy: "independent-double-blind.v1";
  approval: "not_approved";
  id: string;
  project_id: string;
  run_id: string;
  ordinal: number;
  subject_hash: string;
  case_hash: string;
  round: number;
  revision: number;
  status: TaskStatus;
  created_at_ms: number;
  role: "owner" | TaskRole;
  assignment?: TaskAssignment;
  assignments?: TaskAssignment[];
}
export interface ReviewTaskPage {
  tasks: ReviewTask[];
  offset: number;
  limit: number;
}
export interface TaskHumanDecision {
  task_id: string;
  round: number;
  role: TaskRole;
  actor: string;
  subject_hash: string;
  created_at_ms: number;
  decision: ReviewDecision;
  note: string;
}
export interface TaskCase extends Omit<
  ReviewCase,
  "scope" | "reviews" | "review_revision"
> {
  scope: "independent_review_only";
  task_id: string;
  task_revision: number;
  subject_hash: string;
  round: number;
  prior_decisions: TaskHumanDecision[];
}
export interface TaskResult {
  task_id: string;
  round: number;
  decisions: TaskHumanDecision[];
  resolution: {
    schema: "independent-case-resolution.v1";
    scope: "case_resolution_only";
    approval: "not_approved";
    task_id: string;
    round: number;
    subject_hash: string;
    revision: number;
    basis: "unanimous" | "needs_arbitration" | "arbitrated";
    outcome: ReviewDecision;
    decision_hashes: string[];
  };
}
export interface TaskCreatePayload {
  run_id: string;
  ordinal: number;
  case_hash: string;
  reviewer_ids: [string, string];
  arbitrator_id: string;
  share_reference: true;
  confirmed: true;
}
/** Page memory only. Keep across project switches, including unknown writes. */
export interface PendingReviewTask {
  id: string;
  projectId: string;
  payload: TaskCreatePayload;
  task?: ReviewTask;
}
export type PendingReviewTasks = Map<string, PendingReviewTask>;
