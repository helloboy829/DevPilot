import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { EvaluationReviewSummary } from "@/components/workspace/evaluation-review-summary";

const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
const summary = {
  schema: "qa-human-summary.v1",
  scope: "verified_human_summary_preview",
  run_id: "r1",
  run_status: "recording_finished",
  project_id: "p1",
  component_id: "c1",
  component_name: "Synthetic component",
  plan_id: "plan1",
  plan_label: "Plan v1",
  plan_hash: "a".repeat(64),
  summary_hash: "b".repeat(64),
  counts: { pass: 1, fail: 0, uncertain: 0, unreviewed: 1 },
  technical_counts: { collected: 2, other: 0 },
  human_pass_rate: { numerator: 1, denominator: 2, value: 0.5 },
  readiness: "provisional",
  blockers: ["unreviewed"],
  acceptance: "not_approved",
};
beforeEach(() => {
  state.api.mockReset();
  state.api.mockResolvedValue(summary);
});
afterEach(cleanup);
it("does not auto-load; explicitly shows fixed denominator and no acceptance claim", async () => {
  render(<EvaluationReviewSummary projectId="p1" runId="r1" zh={false} />);
  expect(state.api).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh verified summary" }),
  );
  await screen.findByText("50.00%");
  expect(screen.getByText("1 / 2")).toBeTruthy();
  expect(screen.getByText("Unreviewed: 1")).toBeTruthy();
  expect(
    screen.getByText(/not an approved report or acceptance verdict/),
  ).toBeTruthy();
  expect(screen.getByText(/Snapshot preview/)).toBeTruthy();
  expect(state.api.mock.calls).toEqual([
    ["evaluation/projects/p1/review-runs/r1/summary"],
  ]);
});
it("locks duplicate loads and clears a prior number if refresh fails", async () => {
  render(<EvaluationReviewSummary projectId="p1" runId="r1" zh={false} />);
  const button = screen.getByRole("button", {
    name: "Load / refresh verified summary",
  });
  fireEvent.click(button);
  await screen.findByText("50.00%");
  let fail!: (error: Error) => void;
  state.api.mockImplementation(
    () =>
      new Promise((_, reject) => {
        fail = reject;
      }),
  );
  fireEvent.click(button);
  fireEvent.click(button);
  expect(state.api).toHaveBeenCalledTimes(2);
  expect(screen.queryByText("50.00%")).toBeNull();
  await act(async () => fail(new Error("SYNTHETIC_PRIVATE_FAILURE")));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText(/SYNTHETIC_PRIVATE_FAILURE/)).toBeNull();
  expect(screen.queryByText("50.00%")).toBeNull();
});
it("does not label complete review as automatic project PASS", async () => {
  state.api.mockResolvedValue({
    ...summary,
    readiness: "review_complete",
    counts: { pass: 1, fail: 1, uncertain: 0, unreviewed: 0 },
    blockers: [],
  });
  render(<EvaluationReviewSummary projectId="p1" runId="r1" zh={true} />);
  fireEvent.click(
    screen.getByRole("button", { name: "加载 / 刷新已验证汇总" }),
  );
  await screen.findByText("50.00%");
  expect(screen.getByText(/复核已完成/)).toBeTruthy();
  expect(screen.getByText(/不代表已批准报告或最终验收/)).toBeTruthy();
});
it("ignores late responses after switching run or project", async () => {
  let finish!: (value: unknown) => void;
  state.api.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(
    <EvaluationReviewSummary
      key="p1-r1"
      projectId="p1"
      runId="r1"
      zh={false}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh verified summary" }),
  );
  view.rerender(
    <EvaluationReviewSummary
      key="p2-r2"
      projectId="p2"
      runId="r2"
      zh={false}
    />,
  );
  await act(async () => finish(summary));
  expect(screen.queryByText("50.00%")).toBeNull();
  expect(state.api).toHaveBeenCalledTimes(1);
});

it("shows frozen threshold satisfaction separately from review completion and approval", async () => {
  state.api.mockResolvedValue({
    ...summary,
    criteria_evaluation: {
      scope: "effectiveness_threshold_only",
      criteria: {
        schema: "qa-effectiveness-criteria.v1",
        version_label: "Criteria v1",
        min_pass_rate_bps: 8500,
      },
      status: "not_met",
      blockers: [],
      approval: "not_approved",
    },
  });
  render(<EvaluationReviewSummary projectId="p1" runId="r1" zh={false} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh verified summary" }),
  );
  expect(await screen.findByText(/Criteria v1.*85.00%/)).toBeTruthy();
  expect(
    screen.getByText("Effectiveness threshold not met (not approved)"),
  ).toBeTruthy();
});
