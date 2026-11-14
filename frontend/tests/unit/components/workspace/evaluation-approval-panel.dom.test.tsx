import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { EvaluationApprovalPanel } from "@/components/workspace/evaluation-approval-panel";

const state = rs.hoisted(() => ({
  api: {
    projectApprovals: rs.fn(),
    runApprovals: rs.fn(),
    runAudit: rs.fn(),
    preflight: rs.fn(),
    create: rs.fn(),
  },
}));
rs.mock("@/core/evaluation/approval-api", () => ({ approvalApi: state.api }));

const run = "1".repeat(32);
const assessment = "b".repeat(32);
const hash = "c".repeat(64);
const approver = "00000000-0000-0000-0000-000000000005";
const approval = {
  schema: "qa-run-formal-approval.v1",
  scope: "formal_approval_decision",
  id: "d".repeat(32),
  project_id: "p1",
  run_id: run,
  revision: 1,
  created_at_ms: 1,
  recorded_by: "owner",
  assessment: {
    id: assessment,
    revision: 1,
    assessment_hash: hash,
    summary_hash: "e".repeat(64),
  },
  counts: { pass: 2, fail: 0, uncertain: 0, unreviewed: 0 },
  human_pass_rate: { numerator: 2, denominator: 2, value: 1 },
  criteria: { status: "not_defined" },
  readiness: "review_complete",
  decision: "approved",
  approver_id: approver,
  note: null,
  approval_hash: "f".repeat(64),
} as const;

beforeEach(() => {
  for (const fn of Object.values(state.api)) fn.mockReset();
  rs.stubGlobal("crypto", {
    randomUUID: () => "12345678-1234-4123-8123-123456789abc",
  });
});
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
});

function panel() {
  const pending = new Map<string, string>();
  render(
    <EvaluationApprovalPanel
      pendingApprovals={pending}
      projectId="p1"
      zh={false}
    />,
  );
  return pending;
}

function fillTarget() {
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  fireEvent.change(screen.getByLabelText("Assessment ID"), {
    target: { value: assessment },
  });
  fireEvent.change(screen.getByLabelText("Assessment hash"), {
    target: { value: hash },
  });
  fireEvent.change(screen.getByLabelText("Approver account"), {
    target: { value: approver },
  });
}

it("does not read approvals automatically", () => {
  panel();
  for (const fn of Object.values(state.api)) expect(fn).not.toHaveBeenCalled();
});

it("loads project approvals only after an explicit click", async () => {
  state.api.projectApprovals.mockResolvedValue([
    {
      run_id: run,
      id: "d".repeat(32),
      revision: 2,
      decision: "revoked",
      assessment_id: assessment,
      assessment_hash: hash,
      created_at_ms: 1,
    },
  ]);
  panel();
  fireEvent.click(
    screen.getByRole("button", { name: "Load project approvals" }),
  );
  await screen.findByText(/revision 2 · revoked/);
  expect(state.api.projectApprovals).toHaveBeenCalledWith("p1");
});

it("shows preflight blockers and latest approval", async () => {
  state.api.preflight.mockResolvedValue({
    schema: "qa-approval-preflight.v1",
    scope: "read_only_formal_approval_preflight",
    project_id: "p1",
    run_id: run,
    assessment: { id: assessment, revision: 1, assessment_hash: hash },
    approver_id: approver,
    eligible: false,
    blockers: ["criteria_not_met"],
    readiness: "review_complete",
    criteria: { status: "not_met" },
    separation: {
      approver_not_owner: true,
      approver_not_review_actor: true,
    },
    latest_approval: { revision: 1, decision: "approved" },
    approval: "not_recorded",
  });
  panel();
  fillTarget();
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval eligibility" }),
  );
  await screen.findByText(/Blocked: criteria_not_met/);
  expect(screen.getByText(/latest revision 1 \(approved\)/)).toBeTruthy();
  expect(state.api.preflight).toHaveBeenCalledWith(
    "p1",
    run,
    assessment,
    approver,
  );
});

it("requires explicit consent and records one generated ID", async () => {
  state.api.runApprovals.mockResolvedValue([]);
  state.api.runAudit.mockResolvedValue([]);
  state.api.create.mockResolvedValue(approval);
  panel();
  fillTarget();
  fireEvent.click(
    screen.getByRole("button", { name: "Load run approvals and audit" }),
  );
  await waitFor(() => expect(state.api.runApprovals).toHaveBeenCalled());
  const submit = screen.getByRole("button", {
    name: "Record approval / revocation",
  });
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  expect((submit as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(submit);
  await screen.findByText(/Recorded revision 1 \(approved\)/);
  expect(state.api.create).toHaveBeenCalledTimes(1);
  const [projectId, runId, generated, payload] =
    state.api.create.mock.calls[0]!;
  expect([projectId, runId]).toEqual(["p1", run]);
  expect(generated).toMatch(/^[0-9a-f]{32}$/);
  expect(payload).toEqual({
    assessment_id: assessment,
    assessment_hash: hash,
    expected_previous_revision: 0,
    approver_id: approver,
    decision: "approved",
    confirmed: true,
  });
});

it("keeps an unknown write pending for same-ID reconciliation without retry", async () => {
  state.api.runApprovals.mockResolvedValue([]);
  state.api.runAudit.mockResolvedValue([]);
  state.api.create.mockRejectedValue(new Error("unknown"));
  const pending = panel();
  fillTarget();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(
    screen.getByRole("button", { name: "Record approval / revocation" }),
  );
  await screen.findByRole("alert");
  expect(state.api.create).toHaveBeenCalledTimes(1);
  const generated = state.api.create.mock.calls[0]![2];
  expect(pending.get(`p1:${run}`)).toBe(generated);
  expect(screen.getByRole("status").textContent).toContain(generated);
});
