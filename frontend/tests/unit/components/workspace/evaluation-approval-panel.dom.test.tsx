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
    chainIntegrity: rs.fn(),
    projectChainIntegrity: rs.fn(),
    signoffProgress: rs.fn(),
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

it("selects a run from loaded project metadata without reading it", async () => {
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
  const selector = await screen.findByLabelText("Approval run");
  fireEvent.change(selector, { target: { value: run } });
  expect(screen.getByLabelText<HTMLInputElement>("Run ID").value).toBe(run);
  expect(state.api.runApprovals).not.toHaveBeenCalled();
  expect(state.api.runAudit).not.toHaveBeenCalled();
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
  const submit = screen.getByRole<HTMLButtonElement>("button", {
    name: "Record approval / revocation",
  });
  expect(submit.disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(submit.disabled).toBe(false);
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

it("checks chain integrity only after an explicit click", async () => {
  state.api.chainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain.v1",
    scope: "approval_audit_chain_only",
    status: "verified",
    approvals: 2,
    events: 2,
    blockers: [],
  });
  panel();
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  expect(state.api.chainIntegrity).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval chain integrity" }),
  );
  await screen.findByText("Chain verified: 2 approvals / 2 events");
  expect(state.api.chainIntegrity).toHaveBeenCalledWith("p1", run);
});

it("shows fixed blockers for a broken chain without writing", async () => {
  state.api.chainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain.v1",
    scope: "approval_audit_chain_only",
    status: "broken",
    approvals: 1,
    events: 0,
    blockers: ["event_count_mismatch", "revision_gap"],
  });
  panel();
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval chain integrity" }),
  );
  await screen.findByText("Chain broken: event_count_mismatch, revision_gap");
  expect(state.api.create).not.toHaveBeenCalled();
});

it("clears chain integrity when the run changes", async () => {
  state.api.chainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain.v1",
    scope: "approval_audit_chain_only",
    status: "verified",
    approvals: 1,
    events: 1,
    blockers: [],
  });
  panel();
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval chain integrity" }),
  );
  await screen.findByText("Chain verified: 1 approvals / 1 events");
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: "2".repeat(32) },
  });
  expect(screen.queryByText(/Chain verified/)).toBeNull();
});

it("rejects a malformed run ID before reading the chain", () => {
  panel();
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: "short" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval chain integrity" }),
  );
  expect(screen.getByRole("alert").textContent).toContain(
    "Run ID must be 32 hex.",
  );
  expect(state.api.chainIntegrity).not.toHaveBeenCalled();
});

it("checks project approval chains only after an explicit click", async () => {
  state.api.projectChainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain-summary.v1",
    scope: "project_approval_audit_chains_only",
    status: "verified",
    runs: 2,
    verified_runs: 2,
    broken_runs: 0,
    approvals: 3,
    events: 3,
    blockers: [],
  });
  panel();
  expect(state.api.projectChainIntegrity).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Check project approval chains" }),
  );
  await screen.findByText(
    "Project chains verified: 2 of 2 runs · 3 approvals / 3 events",
  );
  expect(state.api.projectChainIntegrity).toHaveBeenCalledWith("p1");
  expect(state.api.create).not.toHaveBeenCalled();
});

it("shows broken project chains with fixed blockers", async () => {
  state.api.projectChainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain-summary.v1",
    scope: "project_approval_audit_chains_only",
    status: "broken",
    runs: 2,
    verified_runs: 1,
    broken_runs: 1,
    approvals: 2,
    events: 1,
    blockers: ["event_count_mismatch", "orphan_audit"],
  });
  panel();
  fireEvent.click(
    screen.getByRole("button", { name: "Check project approval chains" }),
  );
  await screen.findByText(
    "Project chains broken: 1 of 2 runs · event_count_mismatch, orphan_audit",
  );
  expect(state.api.create).not.toHaveBeenCalled();
});

it("shows an unverifiable project summary as a fixed blocker", async () => {
  state.api.projectChainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain-summary.v1",
    scope: "project_approval_audit_chains_only",
    status: "unverifiable",
    runs: 1200,
    verified_runs: 0,
    broken_runs: 0,
    approvals: 5001,
    events: 5001,
    blockers: ["project_chain_too_long"],
  });
  panel();
  fireEvent.click(
    screen.getByRole("button", { name: "Check project approval chains" }),
  );
  await screen.findByText(
    "Project chains unverifiable: project_chain_too_long",
  );
});

it("clears the project chain summary when the project changes", async () => {
  state.api.projectChainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain-summary.v1",
    scope: "project_approval_audit_chains_only",
    status: "verified",
    runs: 1,
    verified_runs: 1,
    broken_runs: 0,
    approvals: 1,
    events: 1,
    blockers: [],
  });
  const pending = new Map<string, string>();
  const view = render(
    <EvaluationApprovalPanel
      pendingApprovals={pending}
      projectId="p1"
      zh={false}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Check project approval chains" }),
  );
  await screen.findByText(/Project chains verified/);
  view.rerender(
    <EvaluationApprovalPanel
      pendingApprovals={pending}
      projectId="p2"
      zh={false}
    />,
  );
  expect(screen.queryByText(/Project chains verified/)).toBeNull();
});

it("clears a pending ID when an explicit read finds the original ID", async () => {
  const id = "d".repeat(32);
  const pending = new Map([[`p1:${run}`, id]]);
  render(
    <EvaluationApprovalPanel
      pendingApprovals={pending}
      projectId="p1"
      zh={false}
    />,
  );
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  expect(screen.getByText(/Unknown write pending reconciliation/)).toBeTruthy();
  state.api.runApprovals.mockResolvedValue([{ ...approval, id }]);
  state.api.runAudit.mockResolvedValue([]);
  fireEvent.click(
    screen.getByRole("button", { name: "Load run approvals and audit" }),
  );
  await screen.findByText(/revision 1 · approved/);
  expect(pending.has(`p1:${run}`)).toBe(false);
  expect(screen.queryByText(/Unknown write pending reconciliation/)).toBeNull();
});

it("keeps a pending ID when the explicit read does not find it", async () => {
  const id = "d".repeat(32);
  const pending = new Map([[`p1:${run}`, id]]);
  render(
    <EvaluationApprovalPanel
      pendingApprovals={pending}
      projectId="p1"
      zh={false}
    />,
  );
  state.api.runApprovals.mockResolvedValue([
    { ...approval, id: "e".repeat(32) },
  ]);
  state.api.runAudit.mockResolvedValue([]);
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Load run approvals and audit" }),
  );
  await screen.findByText(/revision 1 · approved/);
  expect(pending.get(`p1:${run}`)).toBe(id);
  expect(screen.getByText(/Unknown write pending reconciliation/)).toBeTruthy();
});

it("clears stale chain summaries after a recorded decision", async () => {
  state.api.runApprovals.mockResolvedValue([]);
  state.api.runAudit.mockResolvedValue([]);
  state.api.chainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain.v1",
    scope: "approval_audit_chain_only",
    status: "verified",
    approvals: 0,
    events: 0,
    blockers: [],
  });
  state.api.projectChainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain-summary.v1",
    scope: "project_approval_audit_chains_only",
    status: "verified",
    runs: 0,
    verified_runs: 0,
    broken_runs: 0,
    approvals: 0,
    events: 0,
    blockers: [],
  });
  state.api.create.mockResolvedValue(approval);
  panel();
  fillTarget();
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval chain integrity" }),
  );
  await screen.findByText("Chain verified: 0 approvals / 0 events");
  fireEvent.click(
    screen.getByRole("button", { name: "Check project approval chains" }),
  );
  await screen.findByText(
    "Project chains verified: 0 of 0 runs · 0 approvals / 0 events",
  );
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(
    screen.getByRole("button", { name: "Record approval / revocation" }),
  );
  await screen.findByText(/Recorded revision 1 \(approved\)/);
  expect(screen.queryByText(/Chain verified/)).toBeNull();
  expect(screen.queryByText(/Project chains verified/)).toBeNull();
});

it("clears prior project approvals and run state when the project changes", async () => {
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
  const pending = new Map<string, string>();
  const view = render(
    <EvaluationApprovalPanel
      pendingApprovals={pending}
      projectId="p1"
      zh={false}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Load project approvals" }),
  );
  await screen.findByText(/revision 2 · revoked/);
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  view.rerender(
    <EvaluationApprovalPanel
      pendingApprovals={pending}
      projectId="p2"
      zh={false}
    />,
  );
  expect(screen.queryByText(/revision 2 · revoked/)).toBeNull();
  expect(screen.getByLabelText<HTMLInputElement>("Run ID").value).toBe("");
});

it("clears stale preflight results when the target changes", async () => {
  state.api.preflight.mockResolvedValue({
    schema: "qa-approval-preflight.v1",
    scope: "read_only_formal_approval_preflight",
    project_id: "p1",
    run_id: run,
    assessment: { id: assessment, revision: 1, assessment_hash: hash },
    approver_id: approver,
    eligible: true,
    blockers: [],
    readiness: "review_complete",
    criteria: { status: "not_defined" },
    separation: {
      approver_not_owner: true,
      approver_not_review_actor: true,
    },
    latest_approval: null,
    approval: "not_recorded",
  });
  panel();
  fillTarget();
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval eligibility" }),
  );
  await screen.findByText(/Eligible/);
  fireEvent.change(screen.getByLabelText("Approver account"), {
    target: { value: "00000000-0000-0000-0000-000000000006" },
  });
  expect(screen.queryByText(/Eligible/)).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval eligibility" }),
  );
  await screen.findByText(/Eligible/);
  fireEvent.change(screen.getByLabelText("Assessment hash"), {
    target: { value: "d".repeat(64) },
  });
  expect(screen.queryByText(/Eligible/)).toBeNull();
});

it("checks approver sign-off progress without asserting a policy", async () => {
  state.api.signoffProgress.mockResolvedValue({
    schema: "qa-approval-signoff.v1",
    scope: "approval_signoff_progress_only",
    policy: "not_defined",
    required_distinct_approvers: null,
    revisions: 2,
    distinct_approvers: 2,
    distinct_approved_approvers: 1,
    approved_revisions: 1,
    revoked_revisions: 1,
    latest_revision: 2,
    latest_decision: "revoked",
    multi_level_satisfied: null,
    blockers: [
      "multi_level_policy_not_defined",
      "approver_login_not_implemented",
    ],
  });
  panel();
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  expect(state.api.signoffProgress).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Check approver sign-off progress",
    }),
  );
  await screen.findByText(
    "Sign-off progress: 2 revisions · 2 distinct approvers · latest revoked",
  );
  expect(screen.getByText(/Policy not defined/)).toBeTruthy();
  expect(screen.getByText("multi_level_policy_not_defined")).toBeTruthy();
  expect(state.api.signoffProgress).toHaveBeenCalledWith("p1", run);
  expect(state.api.create).not.toHaveBeenCalled();
});

it("clears sign-off progress after a recorded decision", async () => {
  state.api.runApprovals.mockResolvedValue([]);
  state.api.runAudit.mockResolvedValue([]);
  state.api.signoffProgress.mockResolvedValue({
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
    blockers: [
      "multi_level_policy_not_defined",
      "approver_login_not_implemented",
    ],
  });
  state.api.create.mockResolvedValue(approval);
  panel();
  fillTarget();
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: "Check approver sign-off progress",
    }),
  );
  await screen.findByText(/Sign-off progress: 0 revisions/);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(
    screen.getByRole("button", { name: "Record approval / revocation" }),
  );
  await screen.findByText(/Recorded revision 1 \(approved\)/);
  expect(screen.queryByText(/Sign-off progress/)).toBeNull();
});

it("updates the project index after a recorded decision", async () => {
  state.api.projectApprovals.mockResolvedValue([
    {
      run_id: run,
      id: "d".repeat(32),
      revision: 1,
      decision: "approved",
      assessment_id: assessment,
      assessment_hash: hash,
      created_at_ms: 1,
    },
  ]);
  state.api.create.mockResolvedValue({
    ...approval,
    id: "e".repeat(32),
    revision: 2,
    decision: "revoked",
    created_at_ms: 2,
  });
  panel();
  fillTarget();
  fireEvent.click(
    screen.getByRole("button", { name: "Load project approvals" }),
  );
  await screen.findByText(`${run} · r1 approved`);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(
    screen.getByRole("button", { name: "Record approval / revocation" }),
  );
  await screen.findByText(/Recorded revision 2 \(revoked\)/);
  expect(screen.getByText(`${run} · r2 revoked`)).toBeTruthy();
  expect(screen.queryByText(`${run} · r1 approved`)).toBeNull();
});

it("invalidates chain and sign-off snapshots on an explicit run reload", async () => {
  state.api.runApprovals.mockResolvedValue([]);
  state.api.runAudit.mockResolvedValue([]);
  state.api.chainIntegrity.mockResolvedValue({
    schema: "qa-approval-chain.v1",
    scope: "approval_audit_chain_only",
    status: "verified",
    approvals: 0,
    events: 0,
    blockers: [],
  });
  state.api.signoffProgress.mockResolvedValue({
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
    blockers: [
      "multi_level_policy_not_defined",
      "approver_login_not_implemented",
    ],
  });
  panel();
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: run },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval chain integrity" }),
  );
  await screen.findByText("Chain verified: 0 approvals / 0 events");
  fireEvent.click(
    screen.getByRole("button", {
      name: "Check approver sign-off progress",
    }),
  );
  await screen.findByText(/Sign-off progress: 0 revisions/);
  fireEvent.click(
    screen.getByRole("button", { name: "Load run approvals and audit" }),
  );
  await screen.findByText("No approvals for this run yet.");
  expect(screen.queryByText(/Chain verified/)).toBeNull();
  expect(screen.queryByText(/Sign-off progress/)).toBeNull();
});

it("revokes explicit consent when the approval target changes", () => {
  panel();
  fillTarget();
  const submit = screen.getByRole<HTMLButtonElement>("button", {
    name: "Record approval / revocation",
  });
  fireEvent.click(screen.getByRole("checkbox"));
  expect(submit.disabled).toBe(false);
  fireEvent.change(screen.getByLabelText("Approver account"), {
    target: { value: "00000000-0000-0000-0000-000000000006" },
  });
  expect(submit.disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(submit.disabled).toBe(false);
  fireEvent.change(screen.getByLabelText("Assessment hash"), {
    target: { value: "d".repeat(64) },
  });
  expect(submit.disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(submit.disabled).toBe(false);
  fireEvent.change(screen.getByLabelText("Assessment ID"), {
    target: { value: "a".repeat(32) },
  });
  expect(submit.disabled).toBe(true);
});

it("clears stale errors when the approval target changes", () => {
  panel();
  fillTarget();
  fireEvent.change(screen.getByLabelText("Assessment hash"), {
    target: { value: "" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Check approval eligibility" }),
  );
  expect(screen.getByRole("alert")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Assessment hash"), {
    target: { value: hash },
  });
  expect(screen.queryByRole("alert")).toBeNull();
});
