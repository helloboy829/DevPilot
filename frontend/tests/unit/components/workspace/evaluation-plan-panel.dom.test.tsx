import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { EvaluationPlanPanel } from "@/components/workspace/evaluation-plan-panel";

const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
const request = {
  id: "r1",
  project_id: "p1",
  component_id: "c1",
  version_label: "Request v1",
  scope: "request_definition_only",
  protected_hash: "a".repeat(64),
};
const dataset = {
  id: "d1",
  project_id: "p1",
  name: "QA v1",
  status: "frozen",
  sample_count: 2,
  revision: 2,
  content_hash: "b".repeat(64),
  purpose: "baseline",
};
const consent = /I confirm freezing this definition only/;
function saved(payload: Record<string, unknown>) {
  const definition = { ...payload };
  delete definition.confirmed;
  return {
    id: "plan1",
    project_id: "p1",
    component_id: "c1",
    request_version_id: "r1",
    dataset_id: "d1",
    version_label: payload.version_label,
    definition_hash: "c".repeat(64),
    definition: {
      ...definition,
      dataset_purpose: "baseline",
      sample_order: "sample_id_ascending_cycle.v1",
      evaluation_policy: "human_review_required.v1",
      preflight: { sample_count: 2, request_count: 2, total_body_bytes: 20 },
    },
  };
}
beforeEach(() => {
  state.api.mockReset();
  state.api.mockImplementation(
    async (route: string, payload?: Record<string, unknown>) => {
      if (route.endsWith("/components"))
        return {
          components: [{ id: "c1", name_at_link: "Fixture", kind: "llm" }],
        };
      if (route.endsWith("/datasets")) return { datasets: [dataset] };
      if (route.endsWith("/request-versions"))
        return { request_versions: [request] };
      if (route.endsWith("/plans"))
        return payload ? saved(payload) : { plans: [] };
      throw new Error("Unexpected route");
    },
  );
});
afterEach(cleanup);
async function ready() {
  fireEvent.click(
    screen.getByRole("button", {
      name: "Load / refresh plan sources",
    }),
  );
  await screen.findByRole("option", { name: /Fixture/ });
  fireEvent.change(screen.getByRole("combobox", { name: "Plan component" }), {
    target: { value: "c1" },
  });
  await screen.findByRole("option", { name: "Request v1" });
  fireEvent.change(screen.getByRole("combobox", { name: "Request version" }), {
    target: { value: "r1" },
  });
  fireEvent.change(
    screen.getByRole("combobox", { name: "QA dataset version" }),
    { target: { value: "d1" } },
  );
  for (const [label, value] of [
    ["Plan version label", "Plan v1"],
    ["Input JSON pointer", "/q"],
    ["Output JSON pointer", "/a"],
  ])
    fireEvent.change(screen.getByLabelText(label!), { target: { value } });
  fireEvent.click(screen.getByRole("checkbox", { name: consent }));
}
const writes = () =>
  state.api.mock.calls.filter(([, payload]) => payload !== undefined);
it("performs no implicit reads, key requests, model calls or writes", () => {
  render(<EvaluationPlanPanel projectId="p1" zh={false} />);
  expect(state.api).not.toHaveBeenCalled();
  expect(screen.getByText(/This does not start testing/)).toBeTruthy();
});
it("locks synchronous repeated submission before a response and revokes confirmation", async () => {
  render(<EvaluationPlanPanel projectId="p1" zh={false} />);
  await ready();
  let finish!: (value: unknown) => void;
  let payload: Record<string, unknown>;
  const original = state.api.getMockImplementation()!;
  state.api.mockImplementation(
    (route: string, body?: Record<string, unknown>) => {
      if (!body) return original(route, body);
      payload = body;
      return new Promise((resolve) => {
        finish = resolve;
      });
    },
  );
  const button = screen.getByRole("button", {
    name: "Freeze plan definition",
  });
  act(() => {
    fireEvent.click(button);
    fireEvent.click(button);
  });
  expect(writes()).toHaveLength(1);
  expect(
    screen.getByRole<HTMLInputElement>("checkbox", { name: consent }).checked,
  ).toBe(false);
  await act(async () => {
    finish(saved(payload!));
  });
  expect(screen.getByRole("status").textContent).toContain(
    "not execution approval",
  );
});
it("preserves form but requires an explicit successful reload after unknown writes", async () => {
  render(<EvaluationPlanPanel projectId="p1" zh={false} />);
  await ready();
  const original = state.api.getMockImplementation()!;
  state.api.mockImplementation(
    (route: string, body?: Record<string, unknown>) =>
      body
        ? Promise.reject(new Error("SYNTHETIC_SECRET"))
        : original(route, body),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Freeze plan definition" }),
  );
  await screen.findByRole("alert");
  expect(screen.getByRole("alert").textContent).not.toContain(
    "SYNTHETIC_SECRET",
  );
  expect(
    screen.getByLabelText<HTMLInputElement>("Plan version label").value,
  ).toBe("Plan v1");
  fireEvent.click(screen.getByRole("checkbox", { name: consent }));
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Freeze plan definition",
    }).disabled,
  ).toBe(true);
  expect(writes()).toHaveLength(1);
  fireEvent.click(
    screen.getByRole("button", {
      name: "Refresh versions and plans",
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("option", { name: "Request v1" })).toBeTruthy(),
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(
    screen.getByRole<HTMLSelectElement>("combobox", {
      name: "Request version",
    }).value,
  ).toBe("");
});
it("cannot write cross-component or stale dataset metadata even with checked confirmation", async () => {
  const original = state.api.getMockImplementation()!;
  state.api.mockImplementation(
    (route: string, body?: Record<string, unknown>) =>
      route.endsWith("/request-versions")
        ? Promise.resolve({
            request_versions: [{ ...request, component_id: "other" }],
          })
        : original(route, body),
  );
  render(<EvaluationPlanPanel projectId="p1" zh={false} />);
  await ready();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Freeze plan definition",
    }).disabled,
  ).toBe(true);
  expect(writes()).toHaveLength(0);
});
it("each editable mapping or limit revokes consent", async () => {
  render(<EvaluationPlanPanel projectId="p1" zh={false} />);
  await ready();
  for (const [label, value] of [
    ["Input JSON pointer", "/ q "],
    ["Output JSON pointer", "/ a "],
    ["Concurrency", "2"],
    ["Request timeout (ms)", "20000"],
    ["Total time limit (ms)", "40000"],
    ["Total request-body budget (bytes)", "2048"],
  ]) {
    fireEvent.change(screen.getByLabelText(label!), { target: { value } });
    expect(
      screen.getByRole<HTMLInputElement>("checkbox", { name: consent }).checked,
    ).toBe(false);
    fireEvent.click(screen.getByRole("checkbox", { name: consent }));
  }
  expect(writes()).toHaveLength(0);
});
