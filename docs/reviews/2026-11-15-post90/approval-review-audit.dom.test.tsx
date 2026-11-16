import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EvaluationApprovalPanel } from "@/components/workspace/evaluation-approval-panel";

const state = rs.hoisted(() => ({ api: {
  projectApprovals: rs.fn(), runApprovals: rs.fn(), runAudit: rs.fn(),
  chainIntegrity: rs.fn(), projectChainIntegrity: rs.fn(), capabilities: rs.fn(),
  signoffProgress: rs.fn(), runAssessments: rs.fn(), preflight: rs.fn(), create: rs.fn(),
} }));
rs.mock("@/core/evaluation/approval-api", () => ({ approvalApi: state.api }));
const run = "1".repeat(32);
const assessment = "b".repeat(32);
const hash = "c".repeat(64);
const approver = "00000000-0000-0000-0000-000000000005";
const row = { id: "d".repeat(32), revision: 1, decision: "approved", approver_id: approver };
beforeEach(() => {
  for (const fn of Object.values(state.api)) fn.mockReset();
  rs.stubGlobal("crypto", { randomUUID: () => "12345678-1234-4123-8123-123456789abc" });
});
afterEach(() => { cleanup(); rs.unstubAllGlobals(); });
function setup() {
  const pending = new Map<string, string>();
  render(<EvaluationApprovalPanel pendingApprovals={pending} projectId="p1" zh={false} />);
  fireEvent.change(screen.getByLabelText("Run ID"), { target: { value: run } });
  fireEvent.change(screen.getByLabelText("Assessment ID"), { target: { value: assessment } });
  fireEvent.change(screen.getByLabelText("Assessment hash"), { target: { value: hash } });
  fireEvent.change(screen.getByLabelText("Approver account"), { target: { value: approver } });
  return pending;
}
function button(name: string) { return screen.getByRole<HTMLButtonElement>("button", { name }); }

it("review: unknown writes must remain read-only on another click", async () => {
  state.api.create.mockRejectedValue(new Error("unknown"));
  state.api.runApprovals.mockResolvedValue([]);
  const pending = setup();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button("Record approval / revocation"));
  await waitFor(() => expect(button("Check approval eligibility").disabled).toBe(false));
  expect(pending.has(`p1:${run}`)).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button("Record approval / revocation"));
  await waitFor(() => expect(button("Check approval eligibility").disabled).toBe(false));
  expect(state.api.create).toHaveBeenCalledTimes(1);
});

it("review: revision CAS uses the latest revision beyond a 100-row page", async () => {
  state.api.runApprovals.mockResolvedValue(Array.from({ length: 100 }, (_, index) => ({
    ...row, id: index.toString(16).padStart(32, "0"), revision: 125 - index,
  })));
  state.api.runAudit.mockResolvedValue([]);
  state.api.create.mockRejectedValue(new Error("conflict"));
  setup();
  fireEvent.click(button("Load run approvals and audit"));
  await waitFor(() => expect(button("Check approval eligibility").disabled).toBe(false));
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button("Record approval / revocation"));
  expect(state.api.create.mock.calls[0]?.[3]?.expected_previous_revision).toBe(125);
});

it("review: switching runs during a read must not leave the panel busy", async () => {
  let resolveRows!: (value: unknown[]) => void;
  state.api.runApprovals.mockImplementation(() => new Promise(resolve => { resolveRows = resolve; }));
  state.api.runAudit.mockResolvedValue([]);
  setup();
  fireEvent.click(button("Load run approvals and audit"));
  fireEvent.change(screen.getByLabelText("Run ID"), { target: { value: "2".repeat(32) } });
  await act(async () => { resolveRows([]); });
  expect(button("Load run approvals and audit").disabled).toBe(false);
});

it("review: changed approver rejects a stale preflight response", async () => {
  let resolvePreflight!: (value: unknown) => void;
  state.api.preflight.mockImplementation(() => new Promise(resolve => { resolvePreflight = resolve; }));
  setup();
  fireEvent.click(button("Check approval eligibility"));
  fireEvent.change(screen.getByLabelText("Approver account"), {
    target: { value: "00000000-0000-0000-0000-000000000006" },
  });
  await act(async () => { resolvePreflight({ eligible: true, blockers: [], latest_approval: null }); });
  expect(screen.queryByText(/Eligible \(explicit confirmation still required\)/)).toBeNull();
});
