import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

import { EvaluationRetestPanel } from "@/components/workspace/evaluation-retest-panel";

import { baseline, retest, runs, archive } from "../../../fixtures/qa-retest";
const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
let savedId = "e".repeat(32);
function respond(route: string, body?: unknown, method?: string): unknown {
  if (route === "evaluation/projects")
    return {
      projects: [
        { id: "p1", name: "Synthetic project" },
        { id: "p2", name: "Other project" },
      ],
    };
  if (route.endsWith("/review-runs")) return { runs };
  if (route.endsWith("/summary"))
    return route.includes(baseline.run_id) ? baseline : retest;
  if (route.endsWith("/retest-archives")) return { comparisons: [] };
  if (method === "PUT") {
    savedId = route.split("/").at(-1)!;
    return archive(savedId);
  }
  if (route.includes("/cases/"))
    return {
      scope: "human_review_only",
      run_id: route.includes(baseline.run_id) ? baseline.run_id : retest.run_id,
      ordinal: 2,
      sample_id: "z",
      case_hash: route.includes(baseline.run_id)
        ? "1".repeat(64)
        : "2".repeat(64),
      input: "SYNTHETIC_INPUT",
      expected: "SYNTHETIC_GOLD",
      output: "SYNTHETIC_OUTPUT",
      review_revision: 2,
    };
  return archive(savedId);
}
beforeEach(() => {
  state.api.mockReset();
  state.api.mockImplementation(respond);
});
afterEach(cleanup);
async function project() {
  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Synthetic project" });
  fireEvent.change(screen.getByRole("combobox", { name: "Retest project" }), {
    target: { value: "p1" },
  });
}
async function selectPair() {
  await project();
  fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
  await screen.findAllByRole("option", { name: /Synthetic v1/ });
  fireEvent.change(screen.getByRole("combobox", { name: "Baseline run" }), {
    target: { value: baseline.run_id },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Retest run" }), {
    target: { value: retest.run_id },
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: "Verify selected summaries",
    }),
  );
  await screen.findByText("1 / 2 → 2 / 2", { exact: true });
}
function save() {
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm/ }));
  fireEvent.click(
    screen.getByRole("button", {
      name: "Verify & archive comparison",
    }),
  );
}
it("explicit sources, fixed denominator, frozen cases and explicit paired evidence", async () => {
  render(<EvaluationRetestPanel zh={false} />);
  expect(state.api).not.toHaveBeenCalled();
  await selectPair();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Verify & archive comparison",
    }).disabled,
  ).toBe(true);
  save();
  await screen.findByText("+50.00 pp", { exact: true });
  expect(state.api.mock.calls.filter((c) => c[2] === "PUT")).toHaveLength(1);
  expect(state.api.mock.calls.find((c) => c[2] === "PUT")![1]).toEqual({
    baseline: { run_id: baseline.run_id, summary_hash: baseline.summary_hash },
    retest: { run_id: retest.run_id, summary_hash: retest.summary_hash },
    confirmed: true,
  });
  expect(screen.getByText("Not approved", { exact: true })).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "Case filter" }), {
    target: { value: "fail_to_pass" },
  });
  const table = screen.getByRole("table", { name: "Frozen sample changes" });
  expect(within(table).getByText("z", { exact: true })).toBeTruthy();
  expect(within(table).queryByText("a", { exact: true })).toBeNull();
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
  fireEvent.click(
    within(table).getByRole("button", { name: "Open evidence z" }),
  );
  await screen.findByText("SYNTHETIC_INPUT", { exact: true });
  expect(screen.getByText("SYNTHETIC_GOLD", { exact: true })).toBeTruthy();
  expect(screen.getAllByText("SYNTHETIC_OUTPUT", { exact: true })).toHaveLength(
    2,
  );
  expect(
    screen.getByText(/Current review revisions may be newer/),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Hide evidence" }));
  expect(screen.queryByText("SYNTHETIC_INPUT")).toBeNull();
});
it("unknown PUT retains ID across project changes and reconciles only by GET", async () => {
  state.api.mockImplementation(
    (route: string, body?: unknown, method?: string) => {
      if (method === "PUT") {
        savedId = route.split("/").at(-1)!;
        throw new Error("SYNTHETIC_PRIVATE_ERROR");
      }
      return respond(route, body, method);
    },
  );
  render(<EvaluationRetestPanel zh={false} />);
  await selectPair();
  save();
  await screen.findByText(savedId, { exact: true });
  expect(screen.queryByText("SYNTHETIC_PRIVATE_ERROR")).toBeNull();
  const picker = screen.getByRole("combobox", { name: "Retest project" });
  fireEvent.change(picker, { target: { value: "p2" } });
  fireEvent.change(picker, { target: { value: "p1" } });
  expect(screen.getByText(savedId, { exact: true })).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Check pending comparison receipt" }),
  );
  await screen.findByText("+50.00 pp", { exact: true });
  expect(state.api.mock.calls.filter((c) => c[2] === "PUT")).toHaveLength(1);
  expect(
    state.api.mock.calls.some(
      (c) => c[0].endsWith(savedId) && c[1] === undefined,
    ),
  ).toBe(true);
});
it("source changes clear viewed hashes and consent", async () => {
  render(<EvaluationRetestPanel zh={false} />);
  await selectPair();
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm/ }));
  fireEvent.change(screen.getByRole("combobox", { name: "Retest run" }), {
    target: { value: baseline.run_id },
  });
  expect(screen.queryByText("1 / 2 → 2 / 2", { exact: true })).toBeNull();
  expect(
    screen.getByRole<HTMLInputElement>("checkbox", { name: /I confirm/ })
      .checked,
  ).toBe(false);
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Verify & archive comparison",
    }).disabled,
  ).toBe(true);
});
it("incomplete summaries cannot be archived", async () => {
  state.api.mockImplementation(
    (route: string, body?: unknown, method?: string) =>
      route.endsWith("/summary")
        ? { ...baseline, readiness: "provisional", blockers: ["unreviewed"] }
        : respond(route, body, method),
  );
  render(<EvaluationRetestPanel zh={false} />);
  await project();
  fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
  await screen.findAllByRole("option", { name: /Synthetic v1/ });
  fireEvent.change(screen.getByRole("combobox", { name: "Baseline run" }), {
    target: { value: baseline.run_id },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Retest run" }), {
    target: { value: retest.run_id },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Verify selected summaries" }),
  );
  await screen.findByRole("alert");
  expect(state.api.mock.calls.filter((c) => c[2] === "PUT")).toHaveLength(0);
});
it("fences late responses on project switches", async () => {
  let release!: (value: unknown) => void;
  state.api.mockImplementation(
    (route: string, body?: unknown, method?: string) =>
      route.endsWith("/review-runs")
        ? new Promise((resolve) => {
            release = resolve;
          })
        : respond(route, body, method),
  );
  render(<EvaluationRetestPanel zh={false} />);
  await project();
  fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Retest project" }), {
    target: { value: "p2" },
  });
  await act(async () => release({ runs }));
  expect(screen.queryByRole("option", { name: /Synthetic v1/ })).toBeNull();
});

it("an unknown receipt remains pending after a failed GET and never resends", async () => {
  state.api.mockImplementation(
    (route: string, body?: unknown, method?: string) => {
      if (method === "PUT") {
        savedId = route.split("/").at(-1)!;
        throw new Error("PRIVATE_NETWORK_ERROR");
      }
      if (route.endsWith("/retest-archives/" + savedId))
        throw new Error("PRIVATE_NOT_FOUND_IS_NOT_PROOF");
      return respond(route, body, method);
    },
  );
  render(<EvaluationRetestPanel zh={false} />);
  await selectPair();
  save();
  await screen.findByText(savedId, { exact: true });
  const reconcile = screen.getByRole("button", {
    name: "Check pending comparison receipt",
  });
  fireEvent.click(reconcile);
  await screen.findByRole("alert");
  expect(screen.getByText(savedId, { exact: true })).toBeTruthy();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Verify & archive comparison",
    }).disabled,
  ).toBe(true);
  expect(screen.queryByText("PRIVATE_NOT_FOUND_IS_NOT_PROOF")).toBeNull();
  expect(state.api.mock.calls.filter((c) => c[2] === "PUT")).toHaveLength(1);
});
it("mismatched paired evidence is never displayed", async () => {
  state.api.mockImplementation(
    (route: string, body?: unknown, method?: string) => {
      const result = respond(route, body, method);
      return route.includes("/cases/")
        ? {
            ...(result as object),
            case_hash: "9".repeat(64),
            input: "PRIVATE_WRONG_CASE",
          }
        : result;
    },
  );
  render(<EvaluationRetestPanel zh={false} />);
  await selectPair();
  save();
  await screen.findByText("+50.00 pp", { exact: true });
  fireEvent.click(screen.getByRole("button", { name: "Open evidence z" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: "Paired evidence" })).toBeNull();
  expect(screen.queryByText("PRIVATE_WRONG_CASE")).toBeNull();
  expect(
    state.api.mock.calls.filter((c) => c[0].includes("/cases/")),
  ).toHaveLength(1);
});

it("changing the case filter fences an in-flight sensitive evidence read", async () => {
  let release!: (value: unknown) => void;
  state.api.mockImplementation(
    (route: string, body?: unknown, method?: string) =>
      route.includes("/cases/") && route.includes(baseline.run_id)
        ? new Promise((resolve) => {
            release = resolve;
          })
        : respond(route, body, method),
  );
  render(<EvaluationRetestPanel zh={false} />);
  await selectPair();
  save();
  await screen.findByText("+50.00 pp", { exact: true });
  fireEvent.click(screen.getByRole("button", { name: "Open evidence z" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Case filter" }), {
    target: { value: "pass_to_pass" },
  });
  await act(async () =>
    release(respond("/review-runs/" + baseline.run_id + "/cases/2")),
  );
  expect(screen.queryByRole("region", { name: "Paired evidence" })).toBeNull();
  expect(screen.queryByText("SYNTHETIC_INPUT")).toBeNull();
  expect(
    state.api.mock.calls.filter((c) => c[0].includes("/cases/")),
  ).toHaveLength(1);
});
