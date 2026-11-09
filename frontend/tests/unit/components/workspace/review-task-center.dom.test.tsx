import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { ReviewTaskCenter } from "@/components/workspace/review-task-center";

import { id, ownerTask, task } from "../../../fixtures/review-task";
const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
beforeEach(() => {
  state.api.mockReset();
});
afterEach(cleanup);
it("explicitly loads metadata only across owned/assigned projects with page-local role/status filters", async () => {
  state.api.mockResolvedValue({
    tasks: [
      task(),
      ownerTask({ id: "e".repeat(32), project_id: "p2", status: "resolved" }),
    ],
    offset: 0,
    limit: 50,
  });
  render(<ReviewTaskCenter zh={false} />);
  expect(state.api).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh my review tasks" }),
  );
  await screen.findByRole("button", { name: "Open task " + id });
  expect(state.api.mock.calls[0]?.[0]).toBe(
    "evaluation/review-tasks?offset=0&limit=50",
  );
  fireEvent.change(screen.getByLabelText("Role filter (loaded page)"), {
    target: { value: "owner" },
  });
  expect(screen.queryByRole("button", { name: "Open task " + id })).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Open task " + "e".repeat(32) }),
  );
  expect(screen.getByLabelText("Independent review task detail")).toBeTruthy();
  expect(state.api).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText("Status filter (loaded page)"), {
    target: { value: "queued" },
  });
  expect(screen.queryByLabelText("Independent review task detail")).toBeNull();
  expect(screen.getByText(/No matching tasks on this page/)).toBeTruthy();
});
it("looks up only exact safe IDs, never reads case or result automatically", async () => {
  state.api.mockResolvedValue(task());
  render(<ReviewTaskCenter zh={false} />);
  const button = screen.getByRole<HTMLButtonElement>("button", {
    name: "Open task metadata by ID",
  });
  fireEvent.change(screen.getByLabelText("Look up task ID"), {
    target: { value: "../x" },
  });
  expect(button.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Look up task ID"), {
    target: { value: id },
  });
  fireEvent.click(button);
  await screen.findByLabelText("Independent review task detail");
  expect(state.api.mock.calls).toEqual([["evaluation/review-tasks/" + id]]);
  fireEvent.change(screen.getByLabelText("Look up task ID"), {
    target: { value: "" },
  });
  expect(screen.queryByLabelText("Independent review task detail")).toBeNull();
});
it("paginates explicitly without polling or global-count claims", async () => {
  state.api.mockResolvedValueOnce({
    tasks: Array.from({ length: 50 }, (_, i) =>
      task({ id: i.toString(16).padStart(32, "0") }),
    ),
    offset: 0,
    limit: 50,
  });
  state.api.mockResolvedValueOnce({ tasks: [], offset: 50, limit: 50 });
  render(<ReviewTaskCenter zh={false} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh my review tasks" }),
  );
  await screen.findByRole("button", { name: "Open task " + "0".repeat(32) });
  fireEvent.click(screen.getByRole("button", { name: "Next task page" }));
  await screen.findByText("Page offset: 50");
  expect(state.api.mock.calls[1]?.[0]).toBe(
    "evaluation/review-tasks?offset=50&limit=50",
  );
  expect(
    screen.getByRole<HTMLButtonElement>("button", { name: "Next task page" })
      .disabled,
  ).toBe(true);
});
it("late queue responses are fenced after unmount", async () => {
  let done!: (value: unknown) => void;
  state.api.mockReturnValue(
    new Promise((resolve) => {
      done = resolve;
    }),
  );
  const view = render(<ReviewTaskCenter zh={false} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh my review tasks" }),
  );
  view.unmount();
  render(<ReviewTaskCenter zh={false} />);
  await act(async () => {
    done({ tasks: [task()], offset: 0, limit: 50 });
  });
  expect(screen.queryByRole("button", { name: "Open task " + id })).toBeNull();
});

it("provides Chinese labels without automatic reads", () => {
  render(<ReviewTaskCenter zh={true} />);
  expect(
    screen.getByRole("button", { name: "加载 / 刷新我的复核任务" }),
  ).toBeTruthy();
  expect(screen.getByLabelText("按任务 ID 查找")).toBeTruthy();
  expect(state.api).not.toHaveBeenCalled();
});
it("rejects malformed task pages before creating unsafe task links", async () => {
  state.api.mockResolvedValue({
    tasks: [task({ id: "../case" })],
    offset: 0,
    limit: 50,
  });
  render(<ReviewTaskCenter zh={false} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh my review tasks" }),
  );
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: /Open task \.\.\// })).toBeNull();
});
