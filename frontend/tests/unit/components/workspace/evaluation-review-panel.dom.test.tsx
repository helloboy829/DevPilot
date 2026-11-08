import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { EvaluationReviewPanel } from "@/components/workspace/evaluation-review-panel";

const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
const run = {
  id: "r1",
  component_name: "Synthetic component",
  plan_label: "Plan v1",
  status: "recording_finished",
  request_count: 2,
};
const entry = {
  ordinal: 1,
  sample_id: "q1",
  state: "observed",
  kind: "output_collected",
  has_output_evidence: true,
  review_decision: null,
  review_revision: 0,
};
const detail = {
  scope: "human_review_only",
  run_id: "r1",
  ordinal: 1,
  sample_id: "q1",
  component_name: "Synthetic component",
  plan_label: "Plan v1",
  input: "SYNTHETIC_INPUT",
  expected: "SYNTHETIC_GOLD",
  output: "<img src=x onerror=alert(1)> SYNTHETIC_OUTPUT",
  source_ref: "synthetic://local",
  slice_tag: "default",
  evidence_hash: "a".repeat(64),
  case_hash: "b".repeat(64),
  state: "observed",
  technical: {
    kind: "output_collected",
    http_status: 200,
    body_bytes: 35,
    elapsed_ms: 10.0,
  },
  review_revision: 0,
  reviews: [],
};
const consent = /I confirm this human decision/;
beforeEach(() => {
  state.api.mockReset();
  state.api.mockImplementation(async (route: string, body?: unknown) => {
    if (route.endsWith("/review-runs")) return { runs: [run] };
    if (route.includes("/cases?"))
      return {
        run,
        cases: [entry],
        counts: { pass: 0, fail: 0, uncertain: 0, unreviewed: 2 },
        offset: 0,
        limit: 100,
      };
    if (route.endsWith("/cases/1")) return detail;
    if (route.endsWith("/reviews") && body)
      return { revision: 1, decision: "pass", case_hash: detail.case_hash };
    throw new Error("Unexpected route");
  });
});
afterEach(cleanup);
async function ready() {
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh review runs" }),
  );
  await screen.findByRole("option", { name: /Synthetic component/ });
  fireEvent.change(screen.getByLabelText("Review run"), {
    target: { value: "r1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load cases" }));
  await screen.findByRole("button", { name: /Open case 1/ });
  fireEvent.click(screen.getByRole("button", { name: /Open case 1/ }));
  await screen.findByText("SYNTHETIC_GOLD");
}
async function confirm() {
  fireEvent.change(screen.getByLabelText("Review note"), {
    target: { value: "SYNTHETIC_REASON" },
  });
  fireEvent.click(screen.getByRole("radio", { name: "Pass" }));
  fireEvent.click(screen.getByRole("checkbox", { name: consent }));
}
const writes = () =>
  state.api.mock.calls.filter(([, body]) => body !== undefined);
it("has no implicit reads or target/model calls and labels technical status honestly", () => {
  render(<EvaluationReviewPanel projectId="p1" zh={false} />);
  expect(state.api).not.toHaveBeenCalled();
  expect(
    screen.getByText(/Technical completion is not quality PASS/),
  ).toBeTruthy();
});
it("opens Q, A, reference and source together only after explicit actions; renders output as text", async () => {
  render(<EvaluationReviewPanel projectId="p1" zh={false} />);
  await ready();
  expect(screen.getByText("SYNTHETIC_INPUT")).toBeTruthy();
  expect(screen.getByText(detail.output)).toBeTruthy();
  expect(screen.getByText("synthetic://local")).toBeTruthy();
  expect(document.querySelector('img[src="x"]')).toBeNull();
  expect(writes()).toHaveLength(0);
});
it("locks double submission and binds the human decision to the opened case revision", async () => {
  render(<EvaluationReviewPanel projectId="p1" zh={false} />);
  await ready();
  await confirm();
  let finish!: (value: unknown) => void;
  const original = state.api.getMockImplementation()!;
  state.api.mockImplementation((route: string, body?: unknown) =>
    body
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : original(route, body),
  );
  const button = screen.getByRole("button", { name: "Save review revision" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(writes()).toHaveLength(1);
  expect(writes()[0]![1]).toEqual({
    case_hash: detail.case_hash,
    expected_revision: 0,
    decision: "pass",
    note: "SYNTHETIC_REASON",
    confirmed: true,
  });
  expect(
    screen.getByLabelText<HTMLTextAreaElement>("Review note").disabled,
  ).toBe(true);
  await act(async () => {
    finish({ revision: 1 });
  });
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
  expect(writes()).toHaveLength(1);
});
it("revokes consent on edits and requires explicit reload after an unknown write", async () => {
  render(<EvaluationReviewPanel projectId="p1" zh={false} />);
  await ready();
  await confirm();
  fireEvent.change(screen.getByLabelText("Review note"), {
    target: { value: "Updated reason" },
  });
  expect(
    screen.getByRole<HTMLInputElement>("checkbox", { name: consent }).checked,
  ).toBe(false);
  fireEvent.click(screen.getByRole("checkbox", { name: consent }));
  const original = state.api.getMockImplementation()!;
  state.api.mockImplementation((route: string, body?: unknown) =>
    body
      ? Promise.reject(new Error("SYNTHETIC_SECRET"))
      : original(route, body),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save review revision" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("alert").textContent).not.toContain(
    "SYNTHETIC_SECRET",
  );
  fireEvent.click(screen.getByRole("checkbox", { name: consent }));
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Save review revision",
    }).disabled,
  ).toBe(true);
  expect(writes()).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Reload case" }));
  await waitFor(() =>
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Reload case" })
        .disabled,
    ).toBe(false),
  );
  expect(
    screen.getByRole<HTMLInputElement>("checkbox", { name: consent }).checked,
  ).toBe(false);
});
it("prevents pass when output evidence is absent even if technical metadata says collected", async () => {
  const original = state.api.getMockImplementation()!;
  state.api.mockImplementation((route: string, body?: unknown) =>
    route.endsWith("/cases/1")
      ? Promise.resolve({ ...detail, output: null, evidence_hash: null })
      : original(route, body),
  );
  render(<EvaluationReviewPanel projectId="p1" zh={false} />);
  await ready();
  expect(
    screen.getByRole<HTMLInputElement>("radio", { name: "Pass" }).disabled,
  ).toBe(true);
  expect(screen.getByText("No immutable output evidence")).toBeTruthy();
});
it("discards sensitive details and pending responses across project changes", async () => {
  const view = render(
    <EvaluationReviewPanel key="p1" projectId="p1" zh={false} />,
  );
  await ready();
  view.rerender(<EvaluationReviewPanel key="p2" projectId="p2" zh={false} />);
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
  expect(screen.queryByText(detail.output)).toBeNull();
  expect(screen.getByLabelText<HTMLSelectElement>("Review run").value).toBe("");
});

it("ignores a sensitive response that completes after leaving its project", async () => {
  const original = state.api.getMockImplementation()!;
  let finish!: (value: unknown) => void;
  state.api.mockImplementation((route: string, body?: unknown) =>
    route.endsWith("/cases/1")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : original(route, body),
  );
  const view = render(
    <EvaluationReviewPanel key="p1" projectId="p1" zh={false} />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh review runs" }),
  );
  await screen.findByRole("option", { name: /Synthetic component/ });
  fireEvent.change(screen.getByLabelText("Review run"), {
    target: { value: "r1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load cases" }));
  await screen.findByRole("button", { name: /Open case 1/ });
  fireEvent.click(screen.getByRole("button", { name: /Open case 1/ }));
  view.rerender(<EvaluationReviewPanel key="p2" projectId="p2" zh={false} />);
  await act(async () => {
    finish(detail);
  });
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
  expect(screen.queryByText(detail.output)).toBeNull();
  expect(writes()).toHaveLength(0);
});
