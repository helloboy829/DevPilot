import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { ReviewTaskAssignment } from "@/components/workspace/review-task-assignment";
import type { PendingReviewTasks } from "@/core/evaluation/task-types";

import { actors, caseData, ownerTask } from "../../../fixtures/review-task";
const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
beforeEach(() => {
  state.api.mockReset();
});
afterEach(cleanup);
function fill() {
  fireEvent.change(screen.getByLabelText("Blind reviewer 1 account ID"), {
    target: { value: actors[0] },
  });
  fireEvent.change(screen.getByLabelText("Blind reviewer 2 account ID"), {
    target: { value: actors[1] },
  });
  fireEvent.change(screen.getByLabelText("Arbitrator account ID"), {
    target: { value: actors[2] },
  });
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I am authorized to share/ }),
  );
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I explicitly confirm creating/ }),
  );
}
function mount(pendingTasks: PendingReviewTasks = new Map(), projectId = "p1") {
  return render(
    <ReviewTaskAssignment
      projectId={projectId}
      caseData={caseData}
      pendingTasks={pendingTasks}
      zh={false}
    />,
  );
}
const writes = () => state.api.mock.calls.filter((c: unknown[]) => c[1]);
it("requires independent IDs, both consents, no directory and no automatic network", async () => {
  state.api.mockImplementation((route: string) =>
    ownerTask({ id: route.split("/").at(-1)! }),
  );
  mount();
  expect(state.api).not.toHaveBeenCalled();
  const create = screen.getByRole<HTMLButtonElement>("button", {
    name: "Create independent review task",
  });
  expect(create.disabled).toBe(true);
  fill();
  fireEvent.change(screen.getByLabelText("Blind reviewer 2 account ID"), {
    target: { value: actors[0] },
  });
  expect(create.disabled).toBe(true);
  expect(
    screen.getByRole<HTMLInputElement>("checkbox", {
      name: /I explicitly confirm creating/,
    }).checked,
  ).toBe(false);
  fill();
  fireEvent.click(create);
  fireEvent.click(create);
  await screen.findByText(/Task receipt confirmed/);
  expect(writes()).toHaveLength(1);
  const payload = writes()[0]?.[1];
  expect(payload).toEqual({
    run_id: "r1",
    ordinal: 1,
    case_hash: caseData.case_hash,
    reviewer_ids: actors.slice(0, 2),
    arbitrator_id: actors[2],
    share_reference: true,
    confirmed: true,
  });
  expect(JSON.stringify(payload)).not.toContain("SYNTHETIC_GOLD");
});
it("keeps unknown creation ID across project switches; 404 never creates a new ID or resends", async () => {
  const pending: PendingReviewTasks = new Map();
  state.api.mockRejectedValue(new Error("uncertain response"));
  let view = mount(pending);
  fill();
  fireEvent.click(
    screen.getByRole("button", { name: "Create independent review task" }),
  );
  await screen.findByRole("alert");
  const receipt = pending.get("p1:r1:1")!;
  expect(receipt.id).toMatch(/^[0-9a-f]{32}$/);
  view.unmount();
  view = mount(pending, "p2");
  expect(screen.queryByText(receipt.id, { exact: false })).toBeNull();
  view.unmount();
  mount(pending);
  expect(screen.getByText("Task ID: " + receipt.id)).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Reconcile same task ID (GET)" }),
  );
  await screen.findByRole("alert");
  expect(writes()).toHaveLength(1);
  expect(
    screen.queryByRole("button", { name: "Create independent review task" }),
  ).toBeNull();
  state.api.mockResolvedValue(ownerTask({ id: receipt.id }));
  fireEvent.click(
    screen.getByRole("button", { name: "Reconcile same task ID (GET)" }),
  );
  await screen.findByText(/Task receipt confirmed/);
  expect(writes()).toHaveLength(1);
  expect(
    state.api.mock.calls
      .slice(1)
      .every(
        (c: unknown[]) =>
          c[0] === "evaluation/review-tasks/" + receipt.id &&
          c[1] === undefined,
      ),
  ).toBe(true);
});
it("late successful receipts stay in parent memory without opening content in another project", async () => {
  let resolve!: (value: unknown) => void;
  state.api.mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const pending: PendingReviewTasks = new Map();
  const view = mount(pending);
  fill();
  fireEvent.click(
    screen.getByRole("button", { name: "Create independent review task" }),
  );
  const receipt = pending.get("p1:r1:1")!;
  view.unmount();
  mount(pending, "p2");
  await act(async () => {
    resolve(ownerTask({ id: receipt.id }));
  });
  expect(pending.get("p1:r1:1")?.task?.id).toBe(receipt.id);
  expect(screen.queryByText(/Task receipt confirmed/)).toBeNull();
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
});
it("a different case/project/actor receipt is never accepted", async () => {
  state.api.mockImplementation((route: string) =>
    ownerTask({ id: route.split("/").at(-1)!, project_id: "p2" }),
  );
  const pending: PendingReviewTasks = new Map();
  mount(pending);
  fill();
  fireEvent.click(
    screen.getByRole("button", { name: "Create independent review task" }),
  );
  await screen.findByRole("alert");
  expect(pending.get("p1:r1:1")?.task).toBeUndefined();
  expect(screen.queryByText(/Task receipt confirmed/)).toBeNull();
});
