import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

const state = rs.hoisted(() => ({
  create: rs.fn(),
  get: rs.fn(),
  actor: "owner",
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: state.actor, needs_setup: false, system_role: "user" },
    isAuthenticated: true,
    isLoading: false,
  }),
}));
rs.mock("@/core/evaluation/approval-requests", () => ({
  signatureApi: { create: state.create, get: state.get },
}));

import { ApprovalRequestAssignment } from "@/components/workspace/approval-request-assignment";

const run = "a".repeat(32),
  assessment = "c".repeat(32),
  hash = "1".repeat(64);
const actor = "00000000-0000-0000-0000-000000000005";
beforeEach(() => {
  state.create.mockReset();
  state.get.mockReset();
  state.actor = "owner";
});
afterEach(cleanup);

const props = {
  projectId: "project-a",
  runId: run,
  assessmentId: assessment,
  assessmentHash: hash,
  approverId: actor,
  zh: false,
};
function fill() {
  fireEvent.click(screen.getByLabelText("Share this pinned aggregate summary"));
  fireEvent.click(screen.getByLabelText("Confirm signature assignment"));
}
test("owner assigns a fixed summary once and unknown writes only GET the original request", async () => {
  const view = render(<ApprovalRequestAssignment {...props} />);
  expect(state.create).not.toHaveBeenCalled();
  fill();
  let reject!: (error: Error) => void;
  state.create.mockReturnValue(
    new Promise((_yes, no) => {
      reject = no;
    }),
  );
  await act(async () => {
    fireEvent.click(
      screen.getByRole("button", { name: "Assign signature request" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Assign signature request" }),
    );
  });
  expect(state.create).toHaveBeenCalledTimes(1);
  const args = state.create.mock.calls[0]!;
  expect(args[0]).toBe("project-a");
  expect(args[1]).toBe(run);
  expect(args[2]).toMatch(/^[0-9a-f]{32}$/);
  expect(args[3]).toEqual(
    expect.objectContaining({
      assessment_id: assessment,
      assessment_hash: hash,
      approver_id: actor,
      share_summary: true,
      confirmed: true,
    }),
  );
  await act(async () => reject(new Error("SYNTHETIC_SECRET")));
  view.rerender(<ApprovalRequestAssignment {...props} projectId="project-b" />);
  state.get.mockRejectedValue(new Error("404"));
  fireEvent.click(
    screen.getByRole("button", { name: "Reconcile original assignment" }),
  );
  await screen.findByText(/Original assignment remains unresolved/);
  expect(state.get).toHaveBeenCalledWith(args[2]);
  expect(state.create).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("SYNTHETIC_SECRET")).toBeNull();

  view.unmount();
  render(<ApprovalRequestAssignment {...props} projectId="project-c" />);
  expect(screen.getByText(new RegExp(args[2]))).toBeTruthy();
  state.get.mockResolvedValue({
    id: args[2],
    project_id: "project-a",
    run_id: run,
    assessment_id: assessment,
    assessment_hash: hash,
    approver_id: actor,
    expires_at_ms: args[3].expires_at_ms,
    status: "pending",
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Reconcile original assignment" }),
  );
  await screen.findByText(/Original assignment reconciled/);
  expect(state.get).toHaveBeenLastCalledWith(args[2]);
  expect(state.create).toHaveBeenCalledTimes(1);
});

test("changing the source revokes both sharing and assignment consent", () => {
  const view = render(<ApprovalRequestAssignment {...props} />);
  fill();
  view.rerender(
    <ApprovalRequestAssignment {...props} assessmentHash={"2".repeat(64)} />,
  );
  expect(
    screen.getByLabelText<HTMLInputElement>(
      "Share this pinned aggregate summary",
    ).checked,
  ).toBe(false);
  expect(
    screen.getByLabelText<HTMLInputElement>("Confirm signature assignment")
      .checked,
  ).toBe(false);
});
