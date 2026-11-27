import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  projects: rs.fn(),
  api: rs.fn(),
  scenarios: rs.fn(),
  createScenario: rs.fn(),
  createRun: rs.fn(),
  listRuns: rs.fn(),
  getRun: rs.fn(),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      workspace: { githubTooltip: "GitHub" },
      breadcrumb: { workspace: "Workspace" },
      sidebar: { reports: "Reports" },
      common: { home: "Home" },
    },
  }),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "account-1" } }),
}));
rs.mock("@/components/ui/sidebar", () => ({ SidebarTrigger: () => null }));
rs.mock("@/core/evaluation/results-api", () => ({
  listResultProjects: mocks.projects,
}));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: mocks.api }));
rs.mock("@/core/evaluation/performance-results-api", () => ({
  listPerformanceScenarios: mocks.scenarios,
  createPerformanceScenario: mocks.createScenario,
  createPerformanceRun: mocks.createRun,
  listPerformanceRuns: mocks.listRuns,
  getPerformanceRun: mocks.getRun,
}));

import PerformanceWorkbench from "@/components/workspace/performance-workbench";

const plan = {
  id: "plan-1",
  project_id: "project-1",
  component_id: "component-1",
  request_version_id: "request-1",
  dataset_id: "dataset-1",
  version_label: "perf-v1",
  scope: "frozen_definition_only",
  definition_hash: "a".repeat(64),
  definition: {
    limits: {
      mode: "performance",
      concurrency: 1,
      request_count: 12,
      timeout_ms: 10_000,
      wall_time_ms: 30_000,
      max_total_body_bytes: 2048,
    },
    preflight: { sample_count: 3, request_count: 12, total_body_bytes: 1024 },
  },
  created_at: "2026-11-25T00:00:00Z",
  created_by: "account-1",
};

const scenario = {
  id: "scenario-1",
  project_id: "project-1",
  component_id: "component-1",
  plan_id: "plan-1",
  definition_hash: "b".repeat(64),
  definition: { profile: { concurrency: 1, measured_request_count: 12 } },
};

beforeEach(() => {
  mocks.projects.mockResolvedValue({
    projects: [{ id: "project-1", name: "Project One" }],
  });
  mocks.api.mockImplementation((route: string) => {
    if (route.endsWith("/components")) {
      return Promise.resolve({
        components: [{ id: "component-1", name_at_link: "Target One" }],
      });
    }
    if (route.endsWith("/plans"))
      return Promise.resolve({
        plans: [
          plan,
          {
            ...plan,
            id: "effectiveness-plan",
            definition: {
              ...plan.definition,
              limits: { ...plan.definition.limits, mode: "effectiveness" },
            },
          },
        ],
      });
    return Promise.resolve({});
  });
  mocks.scenarios.mockResolvedValue({ scenarios: [] });
  mocks.createScenario.mockResolvedValue(scenario);
  mocks.createRun.mockResolvedValue({
    id: "1".repeat(32),
    scenario_id: "scenario-1",
  });
  mocks.listRuns.mockResolvedValue({
    items: [
      {
        id: "2".repeat(32),
        status: "created",
        scenario_id: "scenario-1",
        created_at: "2026-11-25T00:00:00Z",
        population_count: 12,
      },
    ],
    total: 1,
    next_cursor: "opaque-next",
  });
  mocks.getRun.mockResolvedValue({
    id: "1".repeat(32),
    scenario_id: "scenario-1",
  });
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

async function loadPlan() {
  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Project One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "project-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load components" }));
  await screen.findByRole("option", { name: "Target One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Component" }), {
    target: { value: "component-1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Load plans and scenarios" }),
  );
  await screen.findByRole("option", { name: /perf-v1/ });
}

it("does not load owner data on mount and requires explicit scope loads", async () => {
  render(<PerformanceWorkbench />);
  expect(mocks.projects).not.toHaveBeenCalled();
  expect(mocks.api).not.toHaveBeenCalled();
  expect(mocks.scenarios).not.toHaveBeenCalled();

  await loadPlan();
  expect(mocks.api).toHaveBeenCalledWith(
    "evaluation/projects/project-1/components",
  );
  expect(mocks.api).toHaveBeenCalledWith(
    "evaluation/projects/project-1/components/component-1/plans",
  );
  expect(mocks.scenarios).toHaveBeenCalledWith("project-1", "component-1");
  fireEvent.change(
    screen.getByRole("combobox", { name: "Frozen performance plan" }),
    { target: { value: "plan-1" } },
  );
  expect(screen.getByText(/12 measured requests/)).toBeTruthy();
  expect(
    screen
      .getByRole("combobox", { name: "Frozen performance plan" })
      .querySelector('option[value="effectiveness-plan"]'),
  ).toBeNull();
});

it("explicitly lists existing ledgers and reconciles a selected exact run ID", async () => {
  render(<PerformanceWorkbench />);
  expect(mocks.listRuns).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Project One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "project-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load run ledgers" }));

  const runId = "2".repeat(32);
  await screen.findByText(runId);
  expect(mocks.listRuns).toHaveBeenCalledWith("project-1", { limit: 50 });
  fireEvent.click(
    screen.getByRole("button", { name: "Load more run ledgers" }),
  );
  await screen.findByRole("button", { name: "Reconcile exact run ID" });
  expect(mocks.listRuns).toHaveBeenNthCalledWith(2, "project-1", {
    limit: 50,
    cursor: "opaque-next",
  });
  mocks.getRun.mockResolvedValueOnce({
    id: runId,
    scenario_id: "scenario-1",
    status: "completed",
    population_count: 12,
    state_counts: { succeeded: 10, failed: 2 },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Reconcile exact run ID" }),
  );
  await screen.findByText(/original run ID was reconciled/i);
  expect(await screen.findByText("Run status: completed")).toBeTruthy();
  expect(screen.getByText("Run population: 12")).toBeTruthy();
  expect(screen.getByText("succeeded: 10")).toBeTruthy();
  expect(screen.getByText("failed: 2")).toBeTruthy();
  expect(mocks.getRun).toHaveBeenCalledWith("project-1", runId);
  expect(mocks.createRun).not.toHaveBeenCalled();
  expect(
    mocks.api.mock.calls.some(([route]) => String(route).includes("/admit")),
  ).toBe(false);
});
it("requires valid profile and fresh consent, revoking consent when profile or scope changes", async () => {
  render(<PerformanceWorkbench />);
  await loadPlan();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Frozen performance plan" }),
    { target: { value: "plan-1" } },
  );
  fireEvent.change(screen.getByRole("spinbutton", { name: "Concurrency" }), {
    target: { value: "2" },
  });
  expect(
    screen.getByRole("button", { name: "Freeze scenario" }),
  ).toHaveProperty("disabled", true);
  fireEvent.change(screen.getByRole("spinbutton", { name: "Max in flight" }), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /confirm freezing/ }));
  fireEvent.click(screen.getByRole("button", { name: "Freeze scenario" }));
  await screen.findAllByText(/scenario-1/);
  expect(mocks.createScenario).toHaveBeenCalledWith(
    "project-1",
    "component-1",
    expect.objectContaining({
      plan_id: "plan-1",
      confirmed: true,
      profile: expect.objectContaining({ measured_request_count: 12 }),
    }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Create run ledger" }));
  expect(mocks.createRun).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("checkbox", { name: /confirm creating a run ledger/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Create run ledger" }));
  await screen.findByText(/Ledger only/);
  expect(mocks.createRun).toHaveBeenCalledTimes(1);
  expect(mocks.createRun.mock.calls[0]?.[0]).toBe("project-1");
  expect(mocks.createRun.mock.calls[0]?.[1]).toMatchObject({
    run_id: expect.stringMatching(/^[0-9a-f]{32}$/),
    scenario_id: "scenario-1",
    confirmed: true,
  });

  fireEvent.change(screen.getByRole("spinbutton", { name: "Concurrency" }), {
    target: { value: "2" },
  });
  expect(
    screen.getByRole("checkbox", { name: /confirm freezing/ }),
  ).toHaveProperty("checked", false);
  expect(
    screen.getByRole("checkbox", { name: /confirm creating a run ledger/ }),
  ).toHaveProperty("checked", false);
});

it("reconciles an uncertain ledger write by exact ID only and never dispatches", async () => {
  mocks.createRun.mockRejectedValueOnce(new Error("unknown write"));
  render(<PerformanceWorkbench />);
  await loadPlan();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Frozen performance plan" }),
    { target: { value: "plan-1" } },
  );
  fireEvent.click(screen.getByRole("checkbox", { name: /confirm freezing/ }));
  fireEvent.click(screen.getByRole("button", { name: "Freeze scenario" }));
  await screen.findAllByText(/scenario-1/);
  fireEvent.click(
    screen.getByRole("checkbox", { name: /confirm creating a run ledger/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Create run ledger" }));
  await screen.findByRole("button", { name: "Reconcile run ID" });
  const attemptedId = mocks.createRun.mock.calls[0]?.[1].run_id;
  fireEvent.click(screen.getByRole("button", { name: "Reconcile run ID" }));
  await screen.findByText(/reconciled/i);
  expect(mocks.getRun).toHaveBeenCalledTimes(1);
  expect(mocks.getRun).toHaveBeenCalledWith("project-1", attemptedId);
  expect(mocks.createRun).toHaveBeenCalledTimes(1);
  expect(
    mocks.api.mock.calls.some(([route]) => String(route).includes("/admit")),
  ).toBe(false);
  expect(
    mocks.api.mock.calls.some(([route]) => String(route).includes("evidence")),
  ).toBe(false);
});

it("revokes confirmation when the project scope changes", async () => {
  render(<PerformanceWorkbench />);
  await loadPlan();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Frozen performance plan" }),
    { target: { value: "plan-1" } },
  );
  fireEvent.click(screen.getByRole("checkbox", { name: /confirm freezing/ }));
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "" },
  });
  expect(screen.queryByRole("button", { name: "Freeze scenario" })).toBeNull();

  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "project-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load components" }));
  await screen.findByRole("option", { name: "Target One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Component" }), {
    target: { value: "component-1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Load plans and scenarios" }),
  );
  await screen.findByRole("option", { name: /perf-v1/ });
  fireEvent.change(
    screen.getByRole("combobox", { name: "Frozen performance plan" }),
    { target: { value: "plan-1" } },
  );
  expect(
    screen.getByRole("checkbox", { name: /confirm freezing/ }),
  ).toHaveProperty("checked", false);
});

it("blocks a second scenario POST after an uncertain response until an explicit reload", async () => {
  mocks.createScenario.mockRejectedValueOnce(new Error("unknown write"));
  render(<PerformanceWorkbench />);
  await loadPlan();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Frozen performance plan" }),
    { target: { value: "plan-1" } },
  );
  fireEvent.click(screen.getByRole("checkbox", { name: /confirm freezing/ }));
  fireEvent.click(screen.getByRole("button", { name: "Freeze scenario" }));
  await screen.findByText(/Scenario write outcome is uncertain/);
  expect(mocks.createScenario).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "Freeze scenario" }),
  ).toHaveProperty("disabled", true);
  fireEvent.click(
    screen.getByRole("button", { name: "Load plans and scenarios" }),
  );
  await screen.findByRole("option", { name: /perf-v1/ });
  expect(mocks.scenarios).toHaveBeenCalledTimes(2);
  expect(mocks.createScenario).toHaveBeenCalledTimes(1);
});
