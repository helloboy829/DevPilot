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

export interface ApprovalChainIntegrity {
  schema: "qa-approval-chain.v1";
  scope: "approval_audit_chain_only";
  status: "verified" | "broken";
  approvals: number;
  events: number;
  blockers: string[];
}

export interface ApprovalChainSummary {
  schema: "qa-approval-chain-summary.v1";
  scope: "project_approval_audit_chains_only";
  status: "verified" | "broken" | "unverifiable";
  runs: number;
  verified_runs: number;
  broken_runs: number;
  approvals: number;
  events: number;
  blockers: string[];
}

export interface ApprovalSignoffRequirement {
  schema: "qa-signoff-requirement.v1";
  scope: "technical_signoff_requirement_only";
  policy: { defined: boolean; required_distinct_approvers: number | null };
  observed: {
    distinct_approved_approvers: number;
    latest_decision: ApprovalDecision | null;
  };
  satisfied: boolean | null;
  blockers: string[];
  approval: "not_approved";
}

export interface ApprovalSignoffProgress {
  schema: "qa-approval-signoff.v1";
  scope: "approval_signoff_progress_only";
  policy: "not_defined";
  required_distinct_approvers: null;
  revisions: number;
  distinct_approvers: number;
  distinct_approved_approvers: number;
  approved_revisions: number;
  revoked_revisions: number;
  latest_revision: number | null;
  latest_decision: ApprovalDecision | null;
  multi_level_satisfied: null;
  blockers: string[];
  requirement?: ApprovalSignoffRequirement;
}

export interface ApprovalCapabilities {
  schema: "qa-approval-capabilities.v1";
  scope: "approval_capability_diagnostic_only";
  approver_login: "not_implemented";
  owner_records_on_behalf: true;
  multi_level_policy: "advisory_only";
  multi_level_enforcement: "not_implemented";
  notifications: "not_implemented";
  export: "not_implemented";
  approval: "not_authorized";
  blockers: string[];
}

export interface RunAssessment {
  id: string;
  project_id: string;
  run_id: string;
  revision: number;
  created_at_ms: number;
  summary_hash: string;
  assessment_hash: string;
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
  capabilities(projectId: string) {
    return evaluationApi<ApprovalCapabilities>(
      `${projects(projectId)}/approvals/capabilities`,
    );
  },
  projectChainIntegrity(projectId: string) {
    return evaluationApi<ApprovalChainSummary>(
      `${projects(projectId)}/approvals/integrity`,
    );
  },
  runApprovals(projectId: string, runId: string) {
    return evaluationApi<ApprovalView[]>(`${runs(projectId, runId)}/approvals`);
  },
  runAudit(projectId: string, runId: string) {
    return evaluationApi<ApprovalAuditEvent[]>(
      `${runs(projectId, runId)}/approvals/audit`,
    );
  },
  runAssessments(projectId: string, runId: string) {
    return evaluationApi<RunAssessment[]>(
      `${runs(projectId, runId)}/assessments`,
    );
  },
  chainIntegrity(projectId: string, runId: string) {
    return evaluationApi<ApprovalChainIntegrity>(
      `${runs(projectId, runId)}/approvals/integrity`,
    );
  },
  signoffProgress(
    projectId: string,
    runId: string,
    requiredDistinctApprovers?: number,
  ) {
    const query =
      requiredDistinctApprovers === undefined
        ? ""
        : `?required_distinct_approvers=${requiredDistinctApprovers}`;
    return evaluationApi<ApprovalSignoffProgress>(
      `${runs(projectId, runId)}/approvals/sign-off${query}`,
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
