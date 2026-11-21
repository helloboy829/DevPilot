import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  projects: rs.fn(),
  runs: rs.fn(),
  run: rs.fn(),
  cases: rs.fn(),
  detail: rs.fn(),
  grant: rs.fn(),
  evidence: rs.fn(),
  account: { id: "account-1" },
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
  useAuth: () => ({ user: mocks.account }),
}));
rs.mock("@/components/ui/sidebar", () => ({ SidebarTrigger: () => null }));
rs.mock("@/core/evaluation/results-api", () => ({
  listResultProjects: mocks.projects,
  listResultRuns: mocks.runs,
  getResultRun: mocks.run,
  listResultCases: mocks.cases,
  getResultCase: mocks.detail,
  createResponseEvidenceAccess: mocks.grant,
  readResponseEvidence: mocks.evidence,
}));

import EvaluationResultsWorkspace from "@/components/workspace/evaluation-results-workspace";

const run = {
  run_id: "r1",
  project_id: "p1",
  plan_id: "pl1",
  component_id: "c1",
  dataset_id: "d1",
  status: "finished",
  started_at_ms: 1800000000000,
  finished_at_ms: 1800000001000,
  total: 1,
  request_count: 1,
  concurrency: 1,
  verdict: "NOT_EVALUATED",
  blockers: [],
  technical_counts: { succeeded: 1 },
};
const sample = {
  case_id: "case-1",
  ordinal: 1,
  integrity_status: "complete",
  reference_status: "provided",
  dispatch_state: "succeeded",
  kind: "http",
  http_status: 200,
  latency_ms: 12,
  response_bytes: 20,
  output_evidence: { available: true },
  response_evidence: {
    status: "complete",
    hash_scope: "full",
    sha256: "a".repeat(64),
    captured_bytes: 20,
    observed_bytes: 20,
    content_type: "text/html",
  },
};

beforeEach(() => {
  mocks.account.id = "account-1";
  mocks.projects.mockResolvedValue({
    projects: [
      { id: "p1", name: "Project One" },
      { id: "p2", name: "Project Two" },
    ],
  });
  mocks.runs.mockResolvedValue({
    items: [run],
    total: 1,
    matched_total: 1,
    next_cursor: null,
  });
  mocks.run.mockResolvedValue(run);
  mocks.cases.mockResolvedValue({
    items: [sample],
    total: 1,
    matched_total: 1,
    next_cursor: null,
  });
  mocks.detail.mockResolvedValue(sample);
  mocks.grant.mockResolvedValue({
    access_id: "opaque",
    evidence_kind: "response",
    expires_at_ms: 1800000300000,
  });
  mocks.evidence.mockResolvedValue(
    new TextEncoder().encode("<script>not markup</script>"),
  );
});
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

it("loads only on explicit actions and clears captured text when project changes", async () => {
  render(<EvaluationResultsWorkspace />);
  expect(mocks.projects).not.toHaveBeenCalled();
  expect(mocks.runs).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Project One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "p1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
  await screen.findByText(/NOT_EVALUATED/);
  fireEvent.click(screen.getByRole("button", { name: /r1/ }));
  await screen.findByText("Technical states");
  fireEvent.click(screen.getByRole("button", { name: "Load cases" }));
  await screen.findByText("case-1");
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  await screen.findByText("Authorize and view captured response");
  expect(mocks.grant).not.toHaveBeenCalled();
  expect(mocks.evidence).not.toHaveBeenCalled();

  fireEvent.click(
    screen.getByRole("button", {
      name: "Authorize and view captured response",
    }),
  );
  expect(await screen.findByText("<script>not markup</script>")).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
  expect(mocks.grant).toHaveBeenCalledWith("p1", "r1", 1, "a".repeat(64));
  expect(mocks.evidence).toHaveBeenCalledWith("p1", "opaque", 1_048_576);

  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "p2" },
  });
  expect(screen.queryByText("<script>not markup</script>")).toBeNull();
});

it("invalidates the old case cursor and sensitive detail when filters change", async () => {
  mocks.cases
    .mockResolvedValueOnce({
      items: [sample],
      total: 2,
      matched_total: 2,
      next_cursor: "case-cursor",
    })
    .mockResolvedValueOnce({
      items: [{ ...sample, case_id: "case-2", ordinal: 2 }],
      total: 2,
      matched_total: 2,
      next_cursor: null,
    });
  render(<EvaluationResultsWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Project One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "p1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
  await screen.findByRole("button", { name: /r1/ });
  fireEvent.click(screen.getByRole("button", { name: /r1/ }));
  await screen.findByText("Technical states");
  fireEvent.click(screen.getByRole("button", { name: "Load cases" }));
  await screen.findByText("case-1");
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  await screen.findByRole("button", {
    name: "Authorize and view captured response",
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: "Authorize and view captured response",
    }),
  );
  await screen.findByText("<script>not markup</script>");

  fireEvent.change(screen.getByRole("combobox", { name: "dispatch state" }), {
    target: { value: "failed" },
  });
  expect(screen.queryByText("<script>not markup</script>")).toBeNull();
  expect(screen.queryByText("case-1")).toBeNull();
  expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Load cases" }));
  await screen.findByText("case-2");
  expect(mocks.cases).toHaveBeenLastCalledWith("p1", "r1", {
    integrity_status: "",
    dispatch_state: "failed",
    kind: "",
    http_status: "",
    reference_status: "",
  });
});

it("clears stale cases and sensitive detail after a cursor conflict", async () => {
  mocks.cases
    .mockResolvedValueOnce({
      items: [sample],
      total: 2,
      matched_total: 2,
      next_cursor: "stale",
    })
    .mockRejectedValueOnce(new Error("Evaluation operation failed"));
  render(<EvaluationResultsWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Project One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "p1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
  await screen.findByRole("button", { name: /r1/ });
  fireEvent.click(screen.getByRole("button", { name: /r1/ }));
  await screen.findByText("Technical states");
  fireEvent.click(screen.getByRole("button", { name: "Load cases" }));
  await screen.findByText("case-1");
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  await screen.findByRole("button", {
    name: "Authorize and view captured response",
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: "Authorize and view captured response",
    }),
  );
  await screen.findByText("<script>not markup</script>");

  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText("Evaluation operation failed");
  expect(screen.queryByText("case-1")).toBeNull();
  expect(screen.queryByText("<script>not markup</script>")).toBeNull();
});

it("loads the next run page only after an explicit action", async () => {
  mocks.runs
    .mockResolvedValueOnce({
      items: [run],
      total: 2,
      matched_total: 2,
      next_cursor: "cursor-2",
    })
    .mockResolvedValueOnce({
      items: [{ ...run, run_id: "r2" }],
      total: 2,
      matched_total: 2,
      next_cursor: null,
    });
  render(<EvaluationResultsWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Project One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "p1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
  await screen.findByRole("button", { name: /r1/ });
  fireEvent.click(screen.getByRole("button", { name: "Load more runs" }));
  await screen.findByRole("button", { name: /r2/ });
  expect(mocks.runs).toHaveBeenLastCalledWith("p1", { cursor: "cursor-2" });
});

it("clears captured response when the authenticated account changes", async () => {
  const { rerender } = render(<EvaluationResultsWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Project One" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "p1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
  await screen.findByRole("button", { name: /r1/ });
  fireEvent.click(screen.getByRole("button", { name: /r1/ }));
  await screen.findByText("Technical states");
  fireEvent.click(screen.getByRole("button", { name: "Load cases" }));
  await screen.findByText("case-1");
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  await screen.findByRole("button", {
    name: "Authorize and view captured response",
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: "Authorize and view captured response",
    }),
  );
  await screen.findByText("<script>not markup</script>");

  mocks.account.id = "account-2";
  rerender(<EvaluationResultsWorkspace />);
  expect(screen.queryByText("<script>not markup</script>")).toBeNull();
  expect(mocks.projects).toHaveBeenCalledTimes(1);
});
