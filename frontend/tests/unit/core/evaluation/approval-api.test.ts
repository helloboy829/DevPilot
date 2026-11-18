import { beforeEach, expect, test, rs } from "@rstest/core";

const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));

import { approvalApi } from "@/core/evaluation/approval-api";

const approver = "00000000-0000-0000-0000-000000000005";
const assessment = "a".repeat(32);
const approval = "b".repeat(32);

beforeEach(() => {
  state.api.mockReset();
});

test("builds encoded project, run, audit, integrity and preflight routes", async () => {
  const approvalMetadata = {
    id: "b".repeat(32),
    project_id: "project 1",
    run_id: "run/1",
    revision: 1,
    created_at_ms: 1,
    assessment_id: assessment,
    assessment_hash: "c".repeat(64),
    approver_id: approver,
    decision: "approved",
    approval_hash: "d".repeat(64),
  };
  const integrity = {
    schema: "qa-approval-chain.v1",
    scope: "approval_audit_chain_only",
    status: "verified",
    approvals: 0,
    events: 0,
    blockers: [],
  };
  const projectIntegrity = {
    schema: "qa-approval-chain-summary.v1",
    scope: "project_approval_audit_chains_only",
    status: "verified",
    runs: 0,
    verified_runs: 0,
    broken_runs: 0,
    approvals: 0,
    events: 0,
    blockers: [],
  };
  const signoff = {
    schema: "qa-approval-signoff.v1",
    scope: "approval_signoff_progress_only",
    policy: "not_defined",
    required_distinct_approvers: null,
    revisions: 0,
    distinct_approvers: 0,
    distinct_approved_approvers: 0,
    approved_revisions: 0,
    revoked_revisions: 0,
    latest_revision: null,
    latest_decision: null,
    multi_level_satisfied: null,
    blockers: ["multi_level_policy_not_defined"],
  };
  const capabilities = {
    schema: "qa-approval-capabilities.v1",
    scope: "approval_capability_diagnostic_only",
    approver_login: "assigned_request_only",
    owner_records_on_behalf: true,
    multi_level_policy: "advisory_only",
    multi_level_enforcement: "not_implemented",
    notifications: "in_app_only",
    export: "not_implemented",
    approval: "not_authorized",
    blockers: [
      "multi_level_enforcement_not_implemented",
      "external_notification_delivery_not_implemented",
      "approval_export_not_implemented",
    ],
  };
  const assessmentRow = {
    id: assessment,
    project_id: "project 1",
    run_id: "run/1",
    revision: 1,
    created_at_ms: 1,
    summary_hash: "e".repeat(64),
    assessment_hash: "c".repeat(64),
  };
  const preflight = {
    schema: "qa-approval-preflight.v1",
    scope: "read_only_formal_approval_preflight",
    project_id: "project 1",
    run_id: "run/1",
    assessment: {
      id: assessment,
      revision: 1,
      assessment_hash: "c".repeat(64),
    },
    approver_id: approver,
    eligible: true,
    blockers: [],
    readiness: "review_complete",
    criteria: { status: "not_defined" },
    separation: { approver_not_owner: true, approver_not_review_actor: true },
    latest_approval: null,
    approval: "not_recorded",
  };
  state.api
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([approvalMetadata])
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce(integrity)
    .mockResolvedValueOnce(projectIntegrity)
    .mockResolvedValueOnce(signoff)
    .mockResolvedValueOnce(signoff)
    .mockResolvedValueOnce(capabilities)
    .mockResolvedValueOnce([assessmentRow])
    .mockResolvedValueOnce(preflight);

  await approvalApi.projectApprovals("project 1");
  await approvalApi.runApprovals("project 1", "run/1");
  await approvalApi.runAudit("project 1", "run/1");
  await approvalApi.chainIntegrity("project 1", "run/1");
  await approvalApi.projectChainIntegrity("project 1");
  await approvalApi.signoffProgress("project 1", "run/1");
  await approvalApi.signoffProgress("project 1", "run/1", 2);
  await approvalApi.capabilities("project 1");
  await approvalApi.runAssessments("project 1", "run/1");
  await approvalApi.preflight("project 1", "run/1", assessment, approver);

  expect(state.api.mock.calls.map(([route]) => route)).toEqual([
    "evaluation/projects/project%201/approvals",
    "evaluation/projects/project%201/review-runs/run%2F1/approvals",
    "evaluation/projects/project%201/review-runs/run%2F1/approvals/audit",
    "evaluation/projects/project%201/review-runs/run%2F1/approvals/integrity",
    "evaluation/projects/project%201/approvals/integrity",
    "evaluation/projects/project%201/review-runs/run%2F1/approvals/sign-off",
    "evaluation/projects/project%201/review-runs/run%2F1/approvals/sign-off?required_distinct_approvers=2",
    "evaluation/projects/project%201/approvals/capabilities",
    "evaluation/projects/project%201/review-runs/run%2F1/assessments",
    "evaluation/projects/project%201/review-runs/run%2F1/assessments/" +
      assessment +
      "/approval-preflight?approver_id=" +
      approver,
  ]);
});

test("posts the explicit approval payload to the original ID route", async () => {
  const payload = {
    assessment_id: assessment,
    assessment_hash: "c".repeat(64),
    expected_previous_revision: 1,
    approver_id: approver,
    decision: "revoked" as const,
    note: "Synthetic revocation",
    confirmed: true as const,
  };
  state.api.mockResolvedValueOnce({
    schema: "qa-run-formal-approval.v1",
    scope: "formal_approval_decision",
    id: approval,
    project_id: "project 1",
    run_id: "run/1",
    revision: 2,
    created_at_ms: 2,
    recorded_by: "owner",
    policy: {
      id: "independent-double-blind.v1",
      population: "all_frozen_effectiveness_samples",
      source: "immutable_independent_assessment",
      separation: "approver_not_owner_or_independent_reviewer",
    },
    assessment: {
      id: assessment,
      revision: 1,
      assessment_hash: "c".repeat(64),
      summary_hash: "e".repeat(64),
    },
    counts: { pass: 1 },
    technical_counts: { collected: 1 },
    human_pass_rate: { numerator: 1, denominator: 1, value: 1 },
    criteria: { status: "not_defined", approval: "not_approved" },
    readiness: "review_complete",
    decision: "revoked",
    approver_id: approver,
    note: "Synthetic revocation",
    approval_hash: "d".repeat(64),
  });

  await approvalApi.create("project 1", "run/1", approval, payload);

  expect(state.api).toHaveBeenCalledWith(
    "evaluation/projects/project%201/review-runs/run%2F1/approvals/" + approval,
    payload,
    "POST",
    1_048_576,
  );
});

test("rejects full documents, malformed revisions and foreign receipts during metadata reads", async () => {
  const metadata = {
    id: approval,
    project_id: "p1",
    run_id: "r1",
    revision: 125,
    created_at_ms: 1,
    assessment_id: assessment,
    assessment_hash: "c".repeat(64),
    approver_id: approver,
    decision: "approved",
    approval_hash: "d".repeat(64),
  };
  for (const invalid of [
    { ...metadata, revision: 0 },
    { ...metadata, note: "PRIVATE" },
    { ...metadata, project_id: "other" },
    { ...metadata, run_id: "other" },
    { ...metadata, id: "e".repeat(32) },
  ]) {
    state.api.mockResolvedValueOnce(invalid);
    await expect(
      approvalApi.approvalMetadata("p1", "r1", approval),
    ).rejects.toThrow("Invalid approval response");
  }
  state.api.mockResolvedValueOnce(metadata);
  expect(await approvalApi.approvalMetadata("p1", "r1", approval)).toEqual(
    metadata,
  );
  state.api.mockResolvedValueOnce([{ ...metadata, run_id: "other" }]);
  await expect(approvalApi.runApprovals("p1", "r1")).rejects.toThrow(
    "Invalid approval response",
  );
});
