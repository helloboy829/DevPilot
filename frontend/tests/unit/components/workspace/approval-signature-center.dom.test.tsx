import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

const state = rs.hoisted(() => ({
  user: {
    id: "00000000-0000-0000-0000-000000000005",
    system_role: "user",
    needs_setup: false,
  },
  api: {
    inbox: rs.fn(),
    notifications: rs.fn(),
    state: rs.fn(),
    open: rs.fn(),
    view: rs.fn(),
    decide: rs.fn(),
    operation: rs.fn(),
    cancel: rs.fn(),
    create: rs.fn(),
    get: rs.fn(),
  },
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: state.user,
    isAuthenticated: true,
    isLoading: false,
  }),
}));
rs.mock("@/core/evaluation/approval-requests", () => ({
  signatureApi: state.api,
}));

import { ApprovalSignatureCenter } from "@/components/workspace/approval-signature-center";

const receipt = {
  schema: "qa-approval-request.v1" as const,
  id: "d".repeat(32),
  project_id: "project",
  run_id: "a".repeat(32),
  assessment_id: "c".repeat(32),
  assessment_hash: "1".repeat(64),
  approver_id: "00000000-0000-0000-0000-000000000005",
  created_at_ms: 1,
  expires_at_ms: 253402300799000,
  subject_hash: "2".repeat(64),
  revision: 1,
  status: "pending" as const,
  latest_approval_id: null,
};
const requestState = {
  schema: "qa-approval-request-state.v1",
  request: receipt,
  approval_revision: 0,
  effectiveness: {
    schema: "qa-approval-effectiveness.v1",
    status: "pending",
    blockers: [],
  },
};
const opened = {
  schema: "qa-approval-summary-view.v1",
  request_id: receipt.id,
  view_id: "e".repeat(32),
  revision: 1,
  subject_hash: receipt.subject_hash,
  expires_at_ms: receipt.expires_at_ms,
  view_hash: "3".repeat(64),
  summary: {
    counts: { pass: 2, fail: 0, uncertain: 0, unreviewed: 0 },
    technical_counts: { collected: 2, other: 0 },
    human_pass_rate: { numerator: 2, denominator: 2, value: 1 },
    readiness: "review_complete",
    blockers: [],
    summary_hash: "4".repeat(64),
    criteria: { status: "not_defined", approval: "not_approved" },
  },
};
const click = (name: string) =>
  fireEvent.click(screen.getByRole("button", { name }));
async function load() {
  fireEvent.change(screen.getByLabelText("Signature request ID"), {
    target: { value: receipt.id },
  });
  click("Load signature request");
  await screen.findByText("pending", {
    selector: "[data-testid=signature-effectiveness]",
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  state.user = {
    id: receipt.approver_id,
    system_role: "user",
    needs_setup: false,
  };
  Object.values(state.api).forEach((fn) => fn.mockReset());
  state.api.inbox.mockResolvedValue({
    schema: "qa-approval-inbox.v1",
    requests: [receipt],
    truncated: false,
  });
  state.api.state.mockResolvedValue(requestState);
  state.api.open.mockImplementation(async (_source, viewId: string) => ({
    ...opened,
    view_id: viewId,
  }));
});
afterEach(cleanup);

test("ordinary members see signature actions with no automatic request", async () => {
  render(<ApprovalSignatureCenter zh={false} />);
  Object.values(state.api).forEach((fn) => expect(fn).not.toHaveBeenCalled());
  click("Load my signature requests");
  await screen.findByRole("button", { name: `Select signature ${receipt.id}` });
  expect(state.api.inbox).toHaveBeenCalledWith(receipt.approver_id);
  expect(state.api.state).not.toHaveBeenCalled();
});

test("explicit opening and separate confirmation precede a single self signature", async () => {
  const view = render(<ApprovalSignatureCenter zh={false} />);
  await load();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Sign this assessment",
    }).disabled,
  ).toBe(true);
  click("Open assigned summary");
  await screen.findByText("2 / 2", {
    selector: "[data-testid=signature-all-rate]",
  });
  fireEvent.click(screen.getByLabelText("I confirm my own signature"));
  const pending = deferred<typeof receipt>();
  state.api.decide.mockReturnValue(pending.promise);
  await act(async () => {
    click("Sign this assessment");
    click("Sign this assessment");
  });
  expect(state.api.decide).toHaveBeenCalledTimes(1);
  const args = state.api.decide.mock.calls[0]!;
  expect(args[0]).toEqual(receipt);
  expect(args[2]).toBe("approved");
  expect(args[3]).toBe(0);
  expect(args[4]).toMatch(/^[0-9a-f]{32}$/);
  await act(async () => pending.reject(new Error("SYNTHETIC_SECRET")));
  expect(
    screen.getByRole("button", { name: "Reconcile original operation" }),
  ).toBeTruthy();
  expect(screen.queryByText("SYNTHETIC_SECRET")).toBeNull();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Sign this assessment",
    }).disabled,
  ).toBe(true);
  state.api.operation.mockRejectedValue(new Error("not found"));
  click("Reconcile original operation");
  await screen.findByText(/Original operation remains unresolved/);
  expect(state.api.decide).toHaveBeenCalledTimes(1);
  expect(state.api.operation).toHaveBeenCalledWith(receipt.id, args[1]);

  view.unmount();
  render(<ApprovalSignatureCenter zh={false} />);
  expect(
    screen.getByRole("button", { name: "Reconcile original operation" }),
  ).toBeTruthy();
  state.api.operation.mockResolvedValue({
    ...receipt,
    status: "approved",
    revision: 2,
    latest_approval_id: args[1],
  });
  click("Reconcile original operation");
  await screen.findByText(/Original ID reconciled/);
  expect(state.api.operation).toHaveBeenLastCalledWith(receipt.id, args[1]);
  expect(state.api.decide).toHaveBeenCalledTimes(1);
});

test("account switching fences late summary responses and preserves unknown original ID", async () => {
  const view = render(<ApprovalSignatureCenter zh={false} />);
  await load();
  const pending = deferred<typeof opened>();
  state.api.open.mockReturnValue(pending.promise);
  click("Open assigned summary");
  const originalViewId = state.api.open.mock.calls[0]![1];
  state.user = { ...state.user, id: "00000000-0000-0000-0000-000000000006" };
  view.rerender(<ApprovalSignatureCenter zh={false} />);
  await act(async () => pending.reject(new Error("unknown")));
  expect(screen.queryByTestId("signature-all-rate")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Reconcile original operation" }),
  ).toBeNull();
  state.user = { ...state.user, id: receipt.approver_id };
  view.rerender(<ApprovalSignatureCenter zh={false} />);
  state.api.view.mockResolvedValue({ ...opened, view_id: originalViewId });
  click("Reconcile original operation");
  await screen.findByTestId("signature-all-rate");
  expect(state.api.open).toHaveBeenCalledTimes(1);
  expect(state.api.view).toHaveBeenCalledWith(receipt, originalViewId);
});

test("editing the request clears opened summary and confirmation", async () => {
  render(<ApprovalSignatureCenter zh={false} />);
  await load();
  click("Open assigned summary");
  await screen.findByTestId("signature-all-rate");
  fireEvent.click(screen.getByLabelText("I confirm my own signature"));
  fireEvent.change(screen.getByLabelText("Signature request ID"), {
    target: { value: "6".repeat(32) },
  });
  expect(screen.queryByTestId("signature-all-rate")).toBeNull();
  expect(
    screen.getByLabelText<HTMLInputElement>("I confirm my own signature")
      .checked,
  ).toBe(false);
});
