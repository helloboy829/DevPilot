import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  projects: rs.fn(),
  runs: rs.fn(),
  run: rs.fn(),
  metrics: rs.fn(),
  dispatches: rs.fn(),
  grant: rs.fn(),
  evidence: rs.fn(),
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
rs.mock("@/core/evaluation/performance-results-api", () => ({
  listPerformanceRuns: mocks.runs,
  getPerformanceRun: mocks.run,
  getPerformanceMetrics: mocks.metrics,
  listPerformanceDispatches: mocks.dispatches,
  createPerformanceEvidenceAccess: mocks.grant,
  readPerformanceEvidence: mocks.evidence,
}));

import PerformanceResultsWorkspace from "@/components/workspace/performance-results-workspace";

const performanceRun = {
  id: "run-1",
  project_id: "project-1",
  scenario_id: "scenario-1",
  owner_id: "account-1",
  scenario_hash: "a".repeat(64),
  profile_hash: "b".repeat(64),
  manifest_hash: "c".repeat(64),
  population_count: 4,
  status: "incomplete",
  window_start_ns: 100,
  window_end_ns: 1_000_000_100,
  created_at: "2026-11-23T10:00:00Z",
  finished_at: null,
  state_counts: { succeeded: 1, failed: 1, unknown: 1, not_dispatched: 1 },
  metrics: {
    quantile_method: "nearest_rank.v1",
    cohort_count: 1,
    state_counts: { succeeded: 1, failed: 1, unknown: 1, not_dispatched: 1 },
    window_seconds: 1,
    attempt_qps: 1,
    success_qps: 1,
    rate_applicability: "partial",
    output_token_count: 12,
    output_token_throughput: 12,
    token_applicability: "partial",
    successful_latency_ms: {
      n: 1,
      max: 125,
      p50: 125,
      p90: 125,
      p99: 125,
      p99_applicability: "insufficient_samples",
    },
    failed_latency_ms: {
      n: 1,
      max: 300,
      p50: 300,
      p90: 300,
      p99: 300,
      p99_applicability: "insufficient_samples",
    },
    censored_count: 1,
    population_sha256: "d".repeat(64),
  },
};

const dispatch = {
  id: "dispatch-1",
  project_id: "project-1",
  run_id: "run-1",
  ordinal: 0,
  dispatch_id: "ticket-1",
  phase: "measurement",
  sample_id: "sample-1",
  iteration_index: 0,
  profile_step_id: "step-1",
  state: "unknown",
  send_started_ns: null,
  finished_ns: null,
  elapsed_ms: null,
  request_bytes: 128,
  request_sha256: "e".repeat(64),
  response_status: null,
  response_bytes: null,
  response_sha256: null,
  response_capture_status: "not_received",
  response_hash_scope: null,
  captured_response_bytes: null,
  content_type: null,
  content_encoding: null,
  output_tokens: null,
  token_source: null,
};

beforeEach(() => {
  mocks.projects.mockResolvedValue({
    projects: [{ id: "project-1", name: "Project One" }],
  });
  mocks.runs.mockResolvedValue({
    items: [performanceRun],
    total: 1,
    next_cursor: null,
  });
  mocks.run.mockResolvedValue(performanceRun);
  mocks.metrics.mockResolvedValue({
    schema_version: "performance-metrics.v1",
    applicability: "available",
    revision: "d".repeat(64),
    metrics: performanceRun.metrics,
  });
  mocks.dispatches.mockResolvedValue({
    dispatches: [dispatch],
    offset: 0,
    limit: 100,
  });
  mocks.grant.mockResolvedValue({ access_id: "one-time", expires_at_ms: 1 });
  mocks.evidence.mockResolvedValue(new TextEncoder().encode("private"));
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

it("explicitly loads performance ledger and exposes unknown requests without opening evidence", async () => {
  render(<PerformanceResultsWorkspace />);
  expect(mocks.projects).not.toHaveBeenCalled();
  expect(mocks.runs).not.toHaveBeenCalled();
  expect(mocks.metrics).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Project One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "project-1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Load performance runs" }),
  );
  await screen.findByRole("button", { name: /run-1/ });
  fireEvent.click(screen.getByRole("button", { name: /run-1/ }));
  await screen.findByText("Success QPS");
  expect(mocks.metrics).toHaveBeenCalledWith("project-1", "run-1");
  expect(screen.getByText(/Metrics applicability: available/)).toBeTruthy();
  expect(screen.getAllByText("1 req/s").length).toBe(2);
  for (const [label, value] of [
    ["Failed", "1"],
    ["Unknown", "1"],
    ["Rate applicability", "partial"],
    ["Token applicability", "partial"],
    ["Failed latency p50 / p90 / p99", "300 ms / 300 ms / 300 ms"],
    ["Failed latency samples / max", "1 / 300 ms"],
  ] as const) {
    expect(
      screen.getByText(label).parentElement?.querySelector("dd")?.textContent,
    ).toBe(value);
  }

  fireEvent.click(screen.getByRole("button", { name: "Load dispatches" }));
  await screen.findByText("sample-1");
  expect(screen.getAllByText("measurement").length).toBe(2);
  expect(screen.getAllByText("unknown").length).toBe(2);
  expect(mocks.grant).not.toHaveBeenCalled();
  expect(mocks.evidence).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  await screen.findByText("Request SHA-256");
  expect(screen.getByText("e".repeat(64))).toBeTruthy();
  expect(mocks.grant).not.toHaveBeenCalled();
  expect(mocks.evidence).not.toHaveBeenCalled();
});

it("clears the response loading state when closing details during evidence access", async () => {
  let resolveEvidence: ((value: Uint8Array) => void) | undefined;
  mocks.dispatches.mockResolvedValue({
    dispatches: [
      {
        ...dispatch,
        state: "succeeded",
        response_sha256: "f".repeat(64),
        response_capture_status: "complete",
      },
    ],
    offset: 0,
    limit: 100,
  });
  mocks.evidence.mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveEvidence = resolve;
      }),
  );

  render(<PerformanceResultsWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Project One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "project-1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Load performance runs" }),
  );
  await screen.findByRole("button", { name: /run-1/ });
  fireEvent.click(screen.getByRole("button", { name: /run-1/ }));
  await screen.findByText("Success QPS");
  fireEvent.click(screen.getByRole("button", { name: "Load dispatches" }));
  await screen.findByText("sample-1");
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Authorize and view captured response",
    }),
  );
  await screen.findByRole("button", { name: "Reading response…" });
  expect(mocks.evidence).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole("button", { name: "Close details" }));

  expect(
    screen.queryByRole("button", { name: "Reading response…" }),
  ).toBeNull();
  expect(screen.queryByLabelText("Loading")).toBeNull();
  resolveEvidence?.(new TextEncoder().encode("private"));
});
