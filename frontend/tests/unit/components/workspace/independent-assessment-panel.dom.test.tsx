import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

import { IndependentAssessmentPanel } from "@/components/workspace/independent-assessment-panel";
import {
  assessmentKey,
  type PendingAssessments,
} from "@/core/evaluation/assessment-policy";

import {
  assessment,
  assessmentArchive,
  assessmentId,
  assessmentMetadata,
  provisionalAssessment,
} from "../../../fixtures/assessment";
const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
const run = {
  id: "r1",
  component_name: "Synthetic component",
  plan_label: "Frozen plan",
};
beforeEach(() => {
  state.api.mockReset();
  state.api.mockImplementation((route: string) => {
    if (route.endsWith("/review-runs"))
      return { runs: [run, { ...run, id: "r2" }] };
    if (route.endsWith("/independent-assessment")) return assessment();
    if (route.endsWith("/assessments")) return [];
    return assessmentArchive({ id: route.split("/").at(-1)! });
  });
});
afterEach(cleanup);
function mount(pending: PendingAssessments = new Map(), projectId = "p1") {
  return render(
    <IndependentAssessmentPanel
      projectId={projectId}
      zh={false}
      pendingAssessments={pending}
    />,
  );
}
async function click(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}
async function chooseRun(id = "r1") {
  await click("Load / refresh assessment runs");
  fireEvent.change(
    screen.getByRole("combobox", { name: "Independent assessment run" }),
    { target: { value: id } },
  );
}
async function preview() {
  await chooseRun();
  await click("Load / refresh independent preview and revisions");
}
function confirm() {
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I viewed the independent/ }),
  );
}
const writes = () => state.api.mock.calls.filter((c: unknown[]) => c[1]);
const archiveButton = () =>
  screen.getByRole<HTMLButtonElement>("button", {
    name: "Archive independent assessment revision",
  });
it("has no automatic network; requires explicit reads and separate consent; sends only hash and CAS", async () => {
  const pending: PendingAssessments = new Map();
  mount(pending);
  expect(state.api).not.toHaveBeenCalled();
  await preview();
  expect(archiveButton().disabled).toBe(true);
  expect(screen.getByText("1 / 2 · 50.00%")).toBeTruthy();
  confirm();
  expect(archiveButton().disabled).toBe(false);
  await click("Archive independent assessment revision");
  expect(writes()).toHaveLength(1);
  expect(writes()[0]![1]).toEqual({
    summary_hash: "b".repeat(64),
    expected_previous_revision: 0,
    confirmed: true,
  });
  const remembered = pending.get(assessmentKey("p1", "r1"))!;
  expect(remembered.receipt?.id).toBe(remembered.id);
  expect(archiveButton().disabled).toBe(true);
  expect(screen.getByRole("status").textContent).toContain("not approval");
  expect(
    screen.getByRole("region", {
      name: "Opened immutable assessment revision",
    }),
  ).toBeTruthy();
  await click("Load / refresh independent preview and revisions");
  expect(pending.size).toBe(0);
  expect(archiveButton().disabled).toBe(true);
});
it("revokes confirmation on refresh and lookup edits; accepts incomplete zero-threshold archives without approval", async () => {
  state.api.mockImplementation((route: string) =>
    route.endsWith("/review-runs")
      ? { runs: [run] }
      : route.endsWith("/independent-assessment")
        ? provisionalAssessment()
        : route.endsWith("/assessments")
          ? []
          : assessmentArchive({
              id: route.split("/").at(-1)!,
              assessment: provisionalAssessment(),
            }),
  );
  mount();
  await preview();
  confirm();
  fireEvent.change(screen.getByLabelText("Assessment revision ID"), {
    target: { value: assessmentId },
  });
  expect(archiveButton().disabled).toBe(true);
  confirm();
  await click("Load / refresh independent preview and revisions");
  expect(archiveButton().disabled).toBe(true);
  expect(screen.getByText("0 / 2 · 0.00%")).toBeTruthy();
  confirm();
  await click("Archive independent assessment revision");
  expect(writes()).toHaveLength(1);
});
it("double clicks cannot send twice; unknown writes and 404 remain same-ID GET only across project changes", async () => {
  const pending: PendingAssessments = new Map();
  let rejectWrite!: (e: Error) => void;
  state.api.mockImplementation((route: string, payload?: unknown) => {
    if (payload)
      return new Promise((_, reject) => {
        rejectWrite = reject;
      });
    if (route.endsWith("/review-runs")) return { runs: [run] };
    if (route.endsWith("/independent-assessment")) return assessment();
    if (route.endsWith("/assessments")) return [];
    throw new Error("404 SECRET_RAW_ERROR");
  });
  const view = mount(pending);
  await preview();
  confirm();
  await act(async () => {
    fireEvent.click(archiveButton());
    fireEvent.click(archiveButton());
  });
  expect(writes()).toHaveLength(1);
  const id = pending.get(assessmentKey("p1", "r1"))!.id;
  view.rerender(
    <IndependentAssessmentPanel
      projectId="p2"
      zh={false}
      pendingAssessments={pending}
    />,
  );
  await act(async () => rejectWrite(new Error("SECRET_RAW_ERROR")));
  expect(screen.queryByRole("alert")).toBeNull();
  view.rerender(
    <IndependentAssessmentPanel
      projectId="p1"
      zh={false}
      pendingAssessments={pending}
    />,
  );
  // Pending runs remain selectable without re-fetching recent run metadata.
  fireEvent.change(
    screen.getByRole("combobox", { name: "Independent assessment run" }),
    { target: { value: "r1" } },
  );
  await click("Reconcile same assessment ID (GET)");
  expect(state.api.mock.calls.at(-1)).toEqual([
    "evaluation/projects/p1/review-runs/r1/assessments/" + id,
  ]);
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Load / refresh independent preview and revisions",
    }).disabled,
  ).toBe(true);
  expect(archiveButton().disabled).toBe(true);
  expect(writes()).toHaveLength(1);
  expect(screen.getByRole("alert").textContent).not.toContain(
    "SECRET_RAW_ERROR",
  );
});
it("late successful receipt is stored only for original scope and reconciled on return", async () => {
  const pending: PendingAssessments = new Map();
  let finish!: (v: unknown) => void;
  const normal = state.api.getMockImplementation()!;
  state.api.mockImplementation((route: string, payload?: unknown) =>
    payload
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : normal(route),
  );
  const view = mount(pending);
  await preview();
  confirm();
  await act(async () => {
    fireEvent.click(archiveButton());
  });
  const id = pending.get(assessmentKey("p1", "r1"))!.id;
  view.rerender(
    <IndependentAssessmentPanel
      projectId="p2"
      zh={false}
      pendingAssessments={pending}
    />,
  );
  await act(async () => finish(assessmentArchive({ id })));
  expect(screen.queryByRole("status")).toBeNull();
  expect(pending.get(assessmentKey("p1", "r1"))!.receipt?.id).toBe(id);
  view.rerender(
    <IndependentAssessmentPanel
      projectId="p1"
      zh={false}
      pendingAssessments={pending}
    />,
  );
  fireEvent.change(
    screen.getByRole("combobox", { name: "Independent assessment run" }),
    { target: { value: "r1" } },
  );
  expect(screen.getByText(/Receipt confirmed/)).toBeTruthy();
  expect(writes()).toHaveLength(1);
});
it("clears stale preview on read failure, hides raw errors and rejects owner summaries", async () => {
  mount();
  await preview();
  confirm();
  state.api.mockRejectedValue(new Error("SENSITIVE_SECRET"));
  await click("Load / refresh independent preview and revisions");
  expect(screen.queryByText("1 / 2 · 50.00%")).toBeNull();
  expect(archiveButton().disabled).toBe(true);
  expect(screen.getByRole("alert").textContent).not.toContain(
    "SENSITIVE_SECRET",
  );
  state.api.mockResolvedValue({ schema: "qa-human-summary.v1" });
  await click("Load / refresh independent preview and revisions");
  expect(archiveButton().disabled).toBe(true);
});
it("opens pinned historical documents without current preview requests and rejects metadata mismatch", async () => {
  state.api.mockImplementation((route: string) =>
    route.endsWith("/review-runs")
      ? { runs: [run] }
      : route.endsWith("/independent-assessment")
        ? assessment()
        : route.endsWith("/assessments")
          ? [assessmentMetadata()]
          : assessmentArchive(),
  );
  mount();
  await preview();
  const reads = state.api.mock.calls.length;
  await click("Open assessment revision 1");
  expect(state.api.mock.calls.slice(reads)).toEqual([
    ["evaluation/projects/p1/review-runs/r1/assessments/" + assessmentId],
  ]);
  expect(
    within(
      screen.getByRole("region", {
        name: "Opened immutable assessment revision",
      }),
    ).getByText("1 / 2 · 50.00%"),
  ).toBeTruthy();
  state.api.mockResolvedValue(
    assessmentArchive({ assessment_hash: "a".repeat(64) }),
  );
  await click("Open assessment revision 1");
  expect(
    screen.queryByRole("region", {
      name: "Opened immutable assessment revision",
    }),
  ).toBeNull();
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(writes()).toHaveLength(0);
});
it("fences late preview after changing run and blocks the 1000 revision limit", async () => {
  let finish!: (v: unknown) => void;
  state.api.mockImplementation((route: string) =>
    route.endsWith("/review-runs")
      ? { runs: [run, { ...run, id: "r2" }] }
      : route.endsWith("/independent-assessment")
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : [],
  );
  mount();
  await chooseRun();
  await act(async () => {
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load / refresh independent preview and revisions",
      }),
    );
  });
  fireEvent.change(
    screen.getByRole("combobox", { name: "Independent assessment run" }),
    { target: { value: "r2" } },
  );
  await act(async () => finish(assessment()));
  expect(screen.queryByText("1 / 2 · 50.00%")).toBeNull();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Independent assessment run" }),
    { target: { value: "r1" } },
  );
  state.api.mockImplementation((route: string) =>
    route.endsWith("/independent-assessment")
      ? assessment()
      : [{ ...assessmentMetadata(), revision: 1000 }],
  );
  await click("Load / refresh independent preview and revisions");
  expect(
    screen.getByRole<HTMLInputElement>("checkbox").closest("fieldset")
      ?.disabled,
  ).toBe(true);
  expect(archiveButton().disabled).toBe(true);
});
it("renders labels literally without links, images, raw Q/A or sensitive caching", async () => {
  state.api.mockImplementation((route: string) =>
    route.endsWith("/review-runs")
      ? { runs: [run] }
      : route.endsWith("/independent-assessment")
        ? assessment({
            component_name:
              '<img src="https://invalid.example/pixel"> https://invalid.example',
          })
        : [],
  );
  const view = mount();
  await preview();
  expect(view.container.querySelectorAll("img,a")).toHaveLength(0);
  expect(screen.getByText(/<img src=/)).toBeTruthy();
  expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(
    "invalid.example",
  );
});
