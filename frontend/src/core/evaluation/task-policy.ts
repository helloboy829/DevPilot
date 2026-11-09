import type { ReviewCase } from "./review-types";
import type {
  PendingReviewTask,
  ReviewTask,
  TaskCase,
  TaskCreatePayload,
} from "./task-types";

export const taskIdValid = (id: string) => /^[0-9a-f]{32}$/.test(id);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function taskActorsValid(actors: string[]) {
  return (
    actors.length === 3 &&
    new Set(actors).size === 3 &&
    actors.every((id) => uuid.test(id))
  );
}
export function buildTaskCreate(
  caseData: ReviewCase,
  actors: [string, string, string],
): TaskCreatePayload {
  if (!taskActorsValid(actors) || !/^[0-9a-f]{64}$/.test(caseData.case_hash))
    throw new Error("Invalid assignment");
  return {
    run_id: caseData.run_id,
    ordinal: caseData.ordinal,
    case_hash: caseData.case_hash,
    reviewer_ids: [actors[0], actors[1]],
    arbitrator_id: actors[2],
    share_reference: true,
    confirmed: true,
  };
}
export function taskMetadataMatches(task: ReviewTask, id: string) {
  return (
    taskIdValid(id) &&
    task.id === id &&
    /^[0-9a-f]{64}$/.test(task.subject_hash) &&
    /^[0-9a-f]{64}$/.test(task.case_hash) &&
    Number.isInteger(task.round) &&
    task.round >= 1 &&
    task.round <= 10 &&
    Number.isInteger(task.revision) &&
    task.revision >= 1 &&
    task.revision <= 10_000 &&
    ["owner", "reviewer_1", "reviewer_2", "arbitrator"].includes(task.role) &&
    ["queued", "in_review", "escalated", "resolved", "cancelled"].includes(
      task.status,
    ) &&
    task.scope === "independent_review_only" &&
    task.policy === "independent-double-blind.v1" &&
    task.approval === "not_approved"
  );
}
export function taskReceiptMatches(
  task: ReviewTask,
  receipt: PendingReviewTask,
) {
  const p = receipt.payload;
  const actors = [...p.reviewer_ids, p.arbitrator_id];
  const roles = ["reviewer_1", "reviewer_2", "arbitrator"];
  return (
    taskMetadataMatches(task, receipt.id) &&
    task.role === "owner" &&
    task.project_id === receipt.projectId &&
    task.run_id === p.run_id &&
    task.ordinal === p.ordinal &&
    task.case_hash === p.case_hash &&
    task.assignments?.length === 3 &&
    roles.every((role, i) =>
      task.assignments?.some(
        (a) => a.role === role && a.actor_id === actors[i],
      ),
    )
  );
}
export function taskLeaseActive(task: ReviewTask, now = Date.now()) {
  return (
    task.assignment?.status === "active" &&
    task.assignment.role === task.role &&
    task.assignment.lease_until_ms !== null &&
    task.assignment.lease_until_ms > now
  );
}
export function taskPhaseAllowed(task: ReviewTask) {
  return task.role === "arbitrator"
    ? task.status === "escalated"
    : task.role !== "owner" && ["queued", "in_review"].includes(task.status);
}
export function taskCaseMatches(opened: TaskCase, task: ReviewTask) {
  return (
    task.role !== "owner" &&
    opened.scope === "independent_review_only" &&
    opened.task_id === task.id &&
    opened.run_id === task.run_id &&
    opened.ordinal === task.ordinal &&
    opened.subject_hash === task.subject_hash &&
    opened.case_hash === task.case_hash &&
    opened.round === task.round &&
    opened.task_revision === task.revision &&
    (task.role === "arbitrator"
      ? opened.prior_decisions.length === 2 &&
        ["reviewer_1", "reviewer_2"].every((role) =>
          opened.prior_decisions.some(
            (d) =>
              d.role === role &&
              d.task_id === task.id &&
              d.round === task.round &&
              d.subject_hash === task.subject_hash,
          ),
        )
      : opened.prior_decisions.length === 0)
  );
}
export function taskCanPass(opened: TaskCase) {
  return (
    opened.state === "observed" &&
    typeof opened.evidence_hash === "string" &&
    /^[0-9a-f]{64}$/.test(opened.evidence_hash) &&
    typeof opened.output === "string" &&
    opened.technical.kind === "output_collected"
  );
}
