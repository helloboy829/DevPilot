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
  state.api
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce({ status: "verified" })
    .mockResolvedValueOnce({ eligible: true });

  await approvalApi.projectApprovals("project 1");
  await approvalApi.runApprovals("project 1", "run/1");
  await approvalApi.runAudit("project 1", "run/1");
  await approvalApi.chainIntegrity("project 1", "run/1");
  await approvalApi.preflight("project 1", "run/1", assessment, approver);

  expect(state.api.mock.calls.map(([route]) => route)).toEqual([
    "evaluation/projects/project%201/approvals",
    "evaluation/projects/project%201/review-runs/run%2F1/approvals",
    "evaluation/projects/project%201/review-runs/run%2F1/approvals/audit",
    "evaluation/projects/project%201/review-runs/run%2F1/approvals/integrity",
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
  state.api.mockResolvedValueOnce({ revision: 2, decision: "revoked" });

  await approvalApi.create("project 1", "run/1", approval, payload);

  expect(state.api).toHaveBeenCalledWith(
    "evaluation/projects/project%201/review-runs/run%2F1/approvals/" + approval,
    payload,
  );
});
