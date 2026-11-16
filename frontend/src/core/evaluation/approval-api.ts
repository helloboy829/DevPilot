import { z } from "zod";

import { evaluationApi } from "@/core/evaluation/api";

import {
  approvalMetadataSchema,
  projectApprovalSchema,
  auditSchema,
  assessmentSchema,
  preflightSchema,
  chainSchema,
  chainSummarySchema,
  signoffSchema,
  capabilitiesSchema,
  approvalViewSchema,
  type ApprovalDecision,
  type ApprovalMetadata,
} from "./approval-contracts";
export type {
  ApprovalDecision,
  ProjectApproval,
  ApprovalAuditEvent,
  ApprovalPreflight,
  ApprovalChainIntegrity,
  ApprovalChainSummary,
  ApprovalSignoffPolicy,
  ApprovalSignoffRequirement,
  ApprovalSignoffProgress,
  ApprovalCapabilities,
  RunAssessment,
  ApprovalView,
  ApprovalMetadata,
} from "./approval-contracts";
export interface ApprovalCreatePayload {
  assessment_id: string;
  assessment_hash: string;
  expected_previous_revision: number;
  approver_id: string;
  decision: ApprovalDecision;
  note?: string;
  confirmed: true;
}

const invalid = () => new Error("Invalid approval response");
async function request<S extends z.ZodType>(
  route: string,
  schema: S,
  body?: unknown,
): Promise<z.output<S>> {
  const parsed = schema.safeParse(
    await evaluationApi<unknown>(route, body, "POST", 1_048_576),
  );
  if (!parsed.success) throw invalid();
  return parsed.data;
}
function scoped<T extends { project_id: string; run_id: string }>(
  value: T,
  projectId: string,
  runId: string,
): T {
  if (value.project_id !== projectId || value.run_id !== runId) throw invalid();
  return value;
}
const projects = (projectId: string) =>
  `evaluation/projects/${encodeURIComponent(projectId)}`;
const runs = (projectId: string, runId: string) =>
  `${projects(projectId)}/review-runs/${encodeURIComponent(runId)}`;
/** Authenticated, bounded approval protocols. Reads select metadata only. */
export const approvalApi = {
  projectApprovals(projectId: string) {
    return request(
      `${projects(projectId)}/approvals`,
      z.array(projectApprovalSchema).max(200),
    );
  },
  capabilities(projectId: string) {
    return request(
      `${projects(projectId)}/approvals/capabilities`,
      capabilitiesSchema,
    );
  },
  projectChainIntegrity(projectId: string) {
    return request(
      `${projects(projectId)}/approvals/integrity`,
      chainSummarySchema,
    );
  },
  async runApprovals(
    projectId: string,
    runId: string,
  ): Promise<ApprovalMetadata[]> {
    const rows = await request(
      `${runs(projectId, runId)}/approvals`,
      z.array(approvalMetadataSchema).max(100),
    );
    rows.forEach((row) => scoped(row, projectId, runId));
    if (
      new Set(rows.map((row) => row.id)).size !== rows.length ||
      rows.some(
        (row, index) => index > 0 && row.revision >= rows[index - 1]!.revision,
      )
    )
      throw invalid();
    return rows;
  },
  async approvalMetadata(projectId: string, runId: string, approvalId: string) {
    const value = scoped(
      await request(
        `${runs(projectId, runId)}/approvals/${encodeURIComponent(approvalId)}/metadata`,
        approvalMetadataSchema,
      ),
      projectId,
      runId,
    );
    if (value.id !== approvalId) throw invalid();
    return value;
  },
  async runAudit(projectId: string, runId: string) {
    const rows = await request(
      `${runs(projectId, runId)}/approvals/audit`,
      z.array(auditSchema).max(1000),
    );
    rows.forEach((row) => scoped(row, projectId, runId));
    return rows;
  },
  async runAssessments(projectId: string, runId: string) {
    const rows = await request(
      `${runs(projectId, runId)}/assessments`,
      z.array(assessmentSchema).max(100),
    );
    rows.forEach((row) => scoped(row, projectId, runId));
    return rows;
  },
  chainIntegrity(projectId: string, runId: string) {
    return request(
      `${runs(projectId, runId)}/approvals/integrity`,
      chainSchema,
    );
  },
  async signoffProgress(
    projectId: string,
    runId: string,
    requiredDistinctApprovers?: number,
  ) {
    const query =
      requiredDistinctApprovers === undefined
        ? ""
        : `?required_distinct_approvers=${requiredDistinctApprovers}`;
    const value = await request(
      `${runs(projectId, runId)}/approvals/sign-off${query}`,
      signoffSchema,
    );
    if (value.stored_policy && value.stored_policy.project_id !== projectId)
      throw invalid();
    return value;
  },
  async preflight(
    projectId: string,
    runId: string,
    assessmentId: string,
    approverId: string,
  ) {
    const base = `${runs(projectId, runId)}/assessments/${encodeURIComponent(assessmentId)}/approval-preflight`;
    const value = scoped(
      await request(
        `${base}?approver_id=${encodeURIComponent(approverId)}`,
        preflightSchema,
      ),
      projectId,
      runId,
    );
    if (
      value.assessment.id !== assessmentId ||
      value.approver_id !== approverId
    )
      throw invalid();
    return value;
  },
  async create(
    projectId: string,
    runId: string,
    approvalId: string,
    payload: ApprovalCreatePayload,
  ) {
    const value = scoped(
      await request(
        `${runs(projectId, runId)}/approvals/${encodeURIComponent(approvalId)}`,
        approvalViewSchema,
        payload,
      ),
      projectId,
      runId,
    );
    if (
      value.id !== approvalId ||
      value.revision !== payload.expected_previous_revision + 1 ||
      value.assessment.id !== payload.assessment_id ||
      value.assessment.assessment_hash !== payload.assessment_hash ||
      value.approver_id !== payload.approver_id ||
      value.decision !== payload.decision
    )
      throw invalid();
    return value;
  },
};
