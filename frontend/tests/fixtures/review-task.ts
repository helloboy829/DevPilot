import type { ReviewCase } from "@/core/evaluation/review-types";
import type {
  ReviewTask,
  TaskCase,
  TaskHumanDecision,
  TaskResult,
} from "@/core/evaluation/task-types";

export const actors: [string, string, string] = [
  "11111111-1111-4111-8111-111111111111",
  "22222222-2222-4222-8222-222222222222",
  "33333333-3333-4333-8333-333333333333",
];
export const id = "d".repeat(32);
export function task(overrides: Partial<ReviewTask> = {}): ReviewTask {
  return {
    scope: "independent_review_only",
    policy: "independent-double-blind.v1",
    approval: "not_approved",
    id,
    project_id: "p1",
    run_id: "r1",
    ordinal: 1,
    subject_hash: "a".repeat(64),
    case_hash: "b".repeat(64),
    round: 1,
    revision: 1,
    status: "queued",
    created_at_ms: 1800000000000,
    role: "reviewer_1",
    assignment: { role: "reviewer_1", status: "offered", lease_until_ms: null },
    ...overrides,
  };
}
export function ownerTask(overrides: Partial<ReviewTask> = {}) {
  return task({
    role: "owner",
    assignment: undefined,
    assignments: (["reviewer_1", "reviewer_2", "arbitrator"] as const).map(
      (role, i) => ({
        role,
        actor_id: actors[i],
        status: "offered",
        lease_until_ms: null,
      }),
    ),
    ...overrides,
  });
}
export function activeTask(overrides: Partial<ReviewTask> = {}) {
  return task({
    revision: 2,
    status: "in_review",
    assignment: {
      role: "reviewer_1",
      status: "active",
      lease_until_ms: Date.now() + 1_800_000,
    },
    ...overrides,
  });
}
export function blindDecision(
  role: TaskHumanDecision["role"],
  decision: TaskHumanDecision["decision"] = "pass",
): TaskHumanDecision {
  return {
    task_id: id,
    round: 1,
    role,
    actor: actors[role === "reviewer_1" ? 0 : 1],
    subject_hash: "a".repeat(64),
    created_at_ms: 1800000000000,
    decision,
    note: "SYNTHETIC_BLIND_REASON_" + role,
  };
}
export const caseData: ReviewCase = {
  scope: "human_review_only",
  run_id: "r1",
  ordinal: 1,
  sample_id: "q1",
  component_name: "Synthetic component",
  plan_label: "Synthetic plan",
  state: "observed",
  input: "SYNTHETIC_INPUT",
  expected: "SYNTHETIC_GOLD",
  output: "<img src=x onerror=alert(1)> SYNTHETIC_OUTPUT",
  source_ref: "https://invalid.example/private-reference",
  slice_tag: "default",
  evidence_hash: "c".repeat(64),
  case_hash: "b".repeat(64),
  technical: {
    kind: "output_collected",
    http_status: 200,
    body_bytes: 35,
    elapsed_ms: 10,
  },
  review_revision: 0,
  reviews: [],
};
export function taskCase(
  t = activeTask(),
  overrides: Partial<TaskCase> = {},
): TaskCase {
  const { reviews, review_revision, scope, ...base } = caseData;
  void reviews;
  void review_revision;
  void scope;
  return {
    ...base,
    scope: "independent_review_only",
    task_id: t.id,
    task_revision: t.revision,
    subject_hash: t.subject_hash,
    round: t.round,
    prior_decisions: [],
    ...overrides,
  };
}
export function taskResult(
  t = ownerTask({ status: "resolved" }),
  round = 1,
): TaskResult {
  return {
    task_id: t.id,
    round,
    decisions: [blindDecision("reviewer_1"), blindDecision("reviewer_2")].map(
      (d) => ({ ...d, task_id: t.id, round }),
    ),
    resolution: {
      schema: "independent-case-resolution.v1",
      scope: "case_resolution_only",
      approval: "not_approved",
      task_id: t.id,
      round,
      subject_hash: t.subject_hash,
      revision: 1,
      basis: "unanimous",
      outcome: "pass",
      decision_hashes: ["1".repeat(64), "2".repeat(64)],
    },
  };
}
