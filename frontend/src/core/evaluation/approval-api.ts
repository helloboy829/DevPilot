import { evaluationApi } from "@/core/evaluation/api";

export type ApprovalDecision = "approved" | "revoked";

export interface ProjectApproval {
  run_id: string;
  id: string;
  revision: number;
  decision: ApprovalDecision;
  assessment_id: string;
  assessment_hash: string;
  created_at_ms: number;
}

export interface ApprovalAuditEvent {
  project_id: string;
  run_id: string;
  sequence: number;
  approval_id: string;
  revision: number;
  actor: string;
  action: ApprovalDecision;
  subject_hash: string;
  at_ms: number;
}

export interface ApprovalPreflight {
  schema: "qa-approval-preflight.v1";
  scope: "read_only_formal_approval_preflight";
  project_id: string;
  run_id: string;
  assessment: { id: string; revision: number; assessment_hash: string };
  approver_id: string;
  eligible: boolean;
  blockers: string[];
  readiness: string;
  criteria: { status: string };
  separation: {
    approver_not_owner: boolean;
    approver_not_review_actor: boolean;
  };
  latest_approval: { revision: number; decision: ApprovalDecision } | null;
  approval: "not_recorded";
}

export interface ApprovalView {
  schema: "qa-run-formal-approval.v1";
  scope: "formal_approval_decision";
  id: string;
  project_id: string;
  run_id: string;
  revision: number;
  created_at_ms: number;
  recorded_by: string;
  assessment: {
    id: string;
    revision: number;
    assessment_hash: string;
    summary_hash: string;
  };
  counts: Record<string, number>;
  human_pass_rate: { numerator: number; denominator: number; value: number };
  criteria: { status: string };
  readiness: "review_complete";
  decision: ApprovalDecision;
  approver_id: string;
  note: string | null;
  approval_hash: string;
}

export interface ApprovalCreatePayload {
  assessment_id: string;
  assessment_hash: string;
  expected_previous_revision: number;
  approver_id: string;
  decision: ApprovalDecision;
  note?: string;
  confirmed: true;
}

const projects = (projectId: string) =>
  `evaluation/projects/${encodeURIComponent(projectId)}`;
const runs = (projectId: string, runId: string) =>
  `${projects(projectId)}/review-runs/${encodeURIComponent(runId)}`;

/** Metadata-only approval reads; no document, note or evidence is requested. */
export const approvalApi = {
  projectApprovals(projectId: string) {
    return evaluationApi<ProjectApproval[]>(`${projects(projectId)}/approvals`);
  },
  runApprovals(projectId: string, runId: string) {
    return evaluationApi<ApprovalView[]>(`${runs(projectId, runId)}/approvals`);
  },
  runAudit(projectId: string, runId: string) {
    return evaluationApi<ApprovalAuditEvent[]>(
      `${runs(projectId, runId)}/approvals/audit`,
    );
  },
  preflight(
    projectId: string,
    runId: string,
    assessmentId: string,
    approverId: string,
  ) {
    const base = `${runs(projectId, runId)}/assessments/${encodeURIComponent(assessmentId)}/approval-preflight`;
    return evaluationApi<ApprovalPreflight>(
      `${base}?approver_id=${encodeURIComponent(approverId)}`,
    );
  },
  create(
    projectId: string,
    runId: string,
    approvalId: string,
    payload: ApprovalCreatePayload,
  ) {
    return evaluationApi<ApprovalView>(
      `${runs(projectId, runId)}/approvals/${encodeURIComponent(approvalId)}`,
      payload,
    );
  },
};
