import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { EvaluationExecutionPanel } from "@/components/workspace/evaluation-execution-panel";

const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
const component = { id: "c1", name_at_link: "Synthetic component" };
const plan = {
  id: "p1",
  version_label: "Synthetic plan",
  definition_hash: "a".repeat(64),
  definition: {
    limits: {
      request_count: 2,
      concurrency: 2,
      mode: "effectiveness",
      timeout_ms: 1000,
      wall_time_ms: 10000,
    },
  },
};
const execution = {
  id: "e1",
  run_id: "r1",
  state: "queued",
  reservation_held: true,
};
beforeEach(() => {
  state.api.mockReset();
  state.api.mockImplementation(async (route: string, body?: unknown) => {
    if (route.endsWith("/execution-policy"))
      return { enabled: true, max_active_runs: 2, max_reserved_concurrency: 8 };
    if (route.endsWith("/components")) return { components: [component] };
    if (route.endsWith("/plans")) return { plans: [plan] };
    if (route.endsWith("/execution-runs")) return { executions: [execution] };
    if (route.endsWith("/cancel"))
      return { ...execution, state: "interrupted", reservation_held: false };
    if (body) return execution;
    return execution;
  });
});
afterEach(cleanup);
async function ready() {
  fireEvent.click(
    screen.getByRole("button", { name: "Load execution workspace" }),
  );
  await screen.findByRole("option", { name: "Synthetic component" });
  fireEvent.change(screen.getByLabelText("Execution component"), {
    target: { value: "c1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Load executable plans" }),
  );
  await screen.findByRole("option", { name: /Synthetic plan/ });
  fireEvent.change(screen.getByLabelText("Execution plan"), {
    target: { value: "p1" },
  });
}
it("never starts on mount; requires both fresh consents and explicit click", async () => {
  render(<EvaluationExecutionPanel projectId="project" zh={false} />);
  expect(state.api).not.toHaveBeenCalled();
  await ready();
  const button = screen.getByRole("button", {
    name: "Authorize and queue execution",
  });
  expect(button.hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByLabelText(/I am authorized to call/));
  expect(button.hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByLabelText(/I confirm the frozen plan/));
  fireEvent.click(button);
  await screen.findByText(/Execution receipt: e1/);
  const write = state.api.mock.calls.find((call) => call[2] === "PUT");
  expect(write?.[1]).toEqual({
    plan_id: "p1",
    plan_hash: plan.definition_hash,
    confirmed: true,
    target_authorized: true,
  });
  expect(write?.[0]).toMatch(/execution-runs\/[0-9a-f]{32}$/);
  expect(button.hasAttribute("disabled")).toBe(true);
});
it("an uncertain PUT is not repeated and its same client identifier can be inspected", async () => {
  render(<EvaluationExecutionPanel projectId="project" zh={false} />);
  await ready();
  state.api.mockImplementationOnce(async () => {
    throw new Error("unknown commit");
  });
  fireEvent.click(screen.getByLabelText(/I am authorized to call/));
  fireEvent.click(screen.getByLabelText(/I confirm the frozen plan/));
  fireEvent.click(
    screen.getByRole("button", { name: "Authorize and queue execution" }),
  );
  await screen.findByRole("alert");
  const writes = state.api.mock.calls.filter((call) => call[2] === "PUT");
  expect(writes).toHaveLength(1);
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect execution receipt" }),
  );
  await screen.findByText(/Execution receipt: e1/);
  expect(state.api.mock.calls.filter((call) => call[2] === "PUT")).toHaveLength(
    1,
  );
  expect(state.api.mock.calls.at(-1)?.[0]).toBe(writes[0]?.[0]);
});
it("discards late responses after project unmount", async () => {
  let resolve: (value: unknown) => void = () => undefined;
  const original = state.api.getMockImplementation();
  state.api.mockImplementation(async (...args: [string, unknown?, string?]) =>
    args[0].endsWith("/execution-policy")
      ? new Promise((done) => {
          resolve = done;
        })
      : original?.(...args),
  );
  const view = render(
    <EvaluationExecutionPanel key="one" projectId="one" zh={false} />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Load execution workspace" }),
  );
  view.rerender(
    <EvaluationExecutionPanel key="two" projectId="two" zh={false} />,
  );
  await act(async () => {
    resolve({
      enabled: true,
      max_active_runs: 999,
      max_reserved_concurrency: 999,
    });
  });
  await waitFor(() => expect(screen.queryByText(/999/)).toBeNull());
});
it("operator disabled cannot be bypassed by checking consents", async () => {
  const original = state.api.getMockImplementation();
  state.api.mockImplementation(async (...args: [string, unknown?, string?]) =>
    args[0].endsWith("/execution-policy")
      ? { enabled: false }
      : original?.(...args),
  );
  render(<EvaluationExecutionPanel projectId="project" zh={false} />);
  await ready();
  fireEvent.click(screen.getByLabelText(/I am authorized to call/));
  fireEvent.click(screen.getByLabelText(/I confirm the frozen plan/));
  expect(
    screen
      .getByRole("button", { name: "Authorize and queue execution" })
      .hasAttribute("disabled"),
  ).toBe(true);
});
