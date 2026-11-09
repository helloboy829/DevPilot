import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ReviewTaskDetail } from "@/components/workspace/review-task-detail";

import {
  activeTask,
  blindDecision,
  ownerTask,
  task,
  taskCase,
  taskResult,
} from "../../../fixtures/review-task";
const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
beforeEach(() => {
  state.api.mockReset();
});
afterEach(() => {
  cleanup();
  rs.useRealTimers();
});
const actionConsent = () =>
  screen.getByRole("checkbox", { name: /I explicitly confirm the next/ });
const decisionConsent = () =>
  screen.getByRole("checkbox", { name: /I reviewed the current evidence/ });
const open = async () => {
  fireEvent.click(
    screen.getByRole("button", {
      name: "Explicitly open input, output & reference",
    }),
  );
  await screen.findByText("SYNTHETIC_GOLD");
};
const writeCalls = () =>
  state.api.mock.calls.filter((c: unknown[]) => c[1] !== undefined);

it("does not automatically read or write, requires distinct action consent then explicit evidence open", async () => {
  state.api.mockResolvedValue(activeTask());
  render(<ReviewTaskDetail initialTask={task()} zh={false} />);
  expect(state.api).not.toHaveBeenCalled();
  const claim = screen.getByRole<HTMLButtonElement>("button", {
    name: "Claim task (30 minutes)",
  });
  expect(claim.disabled).toBe(true);
  fireEvent.click(actionConsent());
  fireEvent.click(claim);
  await screen.findByText(/My assignment: active/);
  expect(writeCalls()).toHaveLength(1);
  expect(writeCalls()[0]?.[1]).toEqual({
    expected_revision: 1,
    confirmed: true,
  });
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
  expect((actionConsent() as HTMLInputElement).checked).toBe(false);
});
it("renders untrusted Q/A/source as literal text and submits exactly current revision/hash once", async () => {
  const t = activeTask();
  state.api.mockImplementation((route: string, body?: unknown) =>
    body
      ? task({
          revision: 3,
          status: "in_review",
          assignment: {
            role: "reviewer_1",
            status: "submitted",
            lease_until_ms: null,
          },
        })
      : taskCase(t),
  );
  const { container } = render(<ReviewTaskDetail initialTask={t} zh={false} />);
  await open();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("a")).toBeNull();
  expect(
    screen.queryByLabelText("Blind decisions (arbitration only)"),
  ).toBeNull();
  fireEvent.change(screen.getByLabelText("Independent review reason"), {
    target: { value: "SYNTHETIC_REASON" },
  });
  fireEvent.click(screen.getByRole("radio", { name: "Pass" }));
  fireEvent.click(decisionConsent());
  const save = screen.getByRole("button", {
    name: "Append independent decision",
  });
  fireEvent.click(save);
  fireEvent.click(save);
  await screen.findByText(/Immutable human decision appended/);
  expect(writeCalls()).toHaveLength(1);
  expect(writeCalls()[0]?.[1]).toEqual({
    expected_revision: 2,
    subject_hash: t.subject_hash,
    decision: "pass",
    note: "SYNTHETIC_REASON",
    confirmed: true,
  });
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
});
it("editing a decision or note revokes consent", async () => {
  state.api.mockResolvedValue(taskCase());
  render(<ReviewTaskDetail initialTask={activeTask()} zh={false} />);
  await open();
  fireEvent.click(decisionConsent());
  fireEvent.change(screen.getByLabelText("Independent review reason"), {
    target: { value: "changed" },
  });
  expect((decisionConsent() as HTMLInputElement).checked).toBe(false);
  fireEvent.click(decisionConsent());
  fireEvent.click(screen.getByRole("radio", { name: "Fail" }));
  expect((decisionConsent() as HTMLInputElement).checked).toBe(false);
});
it("technical/missing evidence cannot be manually passed", async () => {
  state.api.mockResolvedValue(
    taskCase(undefined, {
      output: null,
      evidence_hash: null,
      state: "delivery_unknown",
      technical: {
        kind: "timeout",
        http_status: null,
        body_bytes: null,
        elapsed_ms: null,
      },
    }),
  );
  render(<ReviewTaskDetail initialTask={activeTask()} zh={false} />);
  await open();
  expect(
    screen.getByRole<HTMLInputElement>("radio", { name: "Pass" }).disabled,
  ).toBe(true);
});
it("unknown write retains the reason, blocks writes and reconciles only by metadata GET", async () => {
  const t = activeTask();
  state.api.mockResolvedValue(taskCase(t));
  render(<ReviewTaskDetail initialTask={t} zh={false} />);
  await open();
  fireEvent.change(screen.getByLabelText("Independent review reason"), {
    target: { value: "DRAFT_RETAINED" },
  });
  fireEvent.click(decisionConsent());
  state.api.mockRejectedValueOnce(new Error("lost response"));
  fireEvent.click(
    screen.getByRole("button", { name: "Append independent decision" }),
  );
  await screen.findByText(/Write outcome unknown/);
  expect(writeCalls()).toHaveLength(1);
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Claim task (30 minutes)",
    }).disabled,
  ).toBe(true);
  state.api.mockResolvedValueOnce(t);
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh task metadata" }),
  );
  await screen.findByText(/Current metadata checked/);
  expect(writeCalls()).toHaveLength(1);
  expect(
    screen.queryByRole("button", { name: "Append independent decision" }),
  ).toBeNull();
  await open();
  expect(
    screen.getByLabelText<HTMLTextAreaElement>("Independent review reason")
      .value,
  ).toBe("DRAFT_RETAINED");
  expect((decisionConsent() as HTMLInputElement).checked).toBe(false);
});
it("rejects stale/mismatched evidence before showing reference content", async () => {
  state.api.mockResolvedValue(taskCase(undefined, { task_revision: 1 }));
  render(<ReviewTaskDetail initialTask={activeTask()} zh={false} />);
  fireEvent.click(
    screen.getByRole("button", {
      name: "Explicitly open input, output & reference",
    }),
  );
  await screen.findByRole("alert");
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
});
it("does not display peer decisions supplied to a blind reviewer", async () => {
  state.api.mockResolvedValue(
    taskCase(undefined, { prior_decisions: [blindDecision("reviewer_2")] }),
  );
  render(<ReviewTaskDetail initialTask={activeTask()} zh={false} />);
  fireEvent.click(
    screen.getByRole("button", {
      name: "Explicitly open input, output & reference",
    }),
  );
  await screen.findByRole("alert");
  expect(screen.queryByText(/SYNTHETIC_BLIND_REASON/)).toBeNull();
});
it("arbitration stays gated until escalated, then explicitly opens two blind decisions", async () => {
  const t = activeTask({
    role: "arbitrator",
    status: "escalated",
    assignment: {
      role: "arbitrator",
      status: "active",
      lease_until_ms: Date.now() + 60_000,
    },
  });
  state.api.mockResolvedValue(
    taskCase(t, {
      prior_decisions: [
        blindDecision("reviewer_1"),
        blindDecision("reviewer_2", "fail"),
      ],
    }),
  );
  const view = render(
    <ReviewTaskDetail initialTask={task({ role: "arbitrator" })} zh={false} />,
  );
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Claim task (30 minutes)",
    }).disabled,
  ).toBe(true);
  view.unmount();
  render(<ReviewTaskDetail initialTask={t} zh={false} />);
  await open();
  expect(
    screen.getByLabelText("Blind decisions (arbitration only)"),
  ).toBeTruthy();
  expect(screen.getByText("SYNTHETIC_BLIND_REASON_reviewer_1")).toBeTruthy();
});
it("lease expiry closes evidence, revokes consent and disables submit without renewal", async () => {
  rs.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
  const t = activeTask({
    assignment: {
      role: "reviewer_1",
      status: "active",
      lease_until_ms: Date.now() + 1000,
    },
  });
  state.api.mockResolvedValue(taskCase(t));
  render(<ReviewTaskDetail initialTask={t} zh={false} />);
  await act(async () => {
    fireEvent.click(
      screen.getByRole("button", {
        name: "Explicitly open input, output & reference",
      }),
    );
  });
  expect(screen.getByText("SYNTHETIC_GOLD")).toBeTruthy();
  fireEvent.click(decisionConsent());
  act(() => {
    rs.advanceTimersByTime(1002);
  });
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Explicitly open input, output & reference",
    }).disabled,
  ).toBe(true);
  expect(writeCalls()).toHaveLength(0);
});
it("late evidence responses cannot repopulate an unmounted task", async () => {
  let finish!: (value: unknown) => void;
  state.api.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const view = render(
    <ReviewTaskDetail initialTask={activeTask()} zh={false} />,
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: "Explicitly open input, output & reference",
    }),
  );
  view.unmount();
  render(
    <ReviewTaskDetail initialTask={task({ id: "e".repeat(32) })} zh={false} />,
  );
  await act(async () => {
    finish(taskCase());
  });
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
});
it("owner reads a specific immutable historical round, never opens reviewer case", async () => {
  const t = ownerTask({ status: "resolved", round: 2, revision: 9 });
  state.api.mockResolvedValue(taskResult(t));
  render(<ReviewTaskDetail initialTask={t} zh={false} />);
  expect(state.api).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", {
      name: "Explicitly open input, output & reference",
    }),
  ).toBeNull();
  fireEvent.change(screen.getByLabelText("Result round"), {
    target: { value: "1" },
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: "Explicitly open round result & reasons",
    }),
  );
  await screen.findByLabelText("Verified historical case resolution");
  expect(state.api.mock.calls[0]?.[0]).toContain("/result?round_number=1");
  fireEvent.change(screen.getByLabelText("Result round"), {
    target: { value: "2" },
  });
  expect(
    screen.queryByLabelText("Verified historical case resolution"),
  ).toBeNull();
});
it("owner reopen requires a reason, explicit confirmation and preserves old round rather than editing decisions", async () => {
  state.api.mockResolvedValue(ownerTask({ round: 2, revision: 4 }));
  render(
    <ReviewTaskDetail
      initialTask={ownerTask({ status: "resolved", revision: 3 })}
      zh={false}
    />,
  );
  const button = screen.getByRole<HTMLButtonElement>("button", {
    name: "Reopen in a new round (retain history)",
  });
  expect(button.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Reopen reason"), {
    target: { value: "SYNTHETIC_NEW_ROUND_REASON" },
  });
  fireEvent.click(actionConsent());
  fireEvent.click(button);
  await screen.findByText(/Task action confirmed/);
  expect(writeCalls()[0]?.[0]).toContain("/reopen");
  expect(writeCalls()[0]?.[1]).toEqual({
    expected_revision: 3,
    confirmed: true,
    reason: "SYNTHETIC_NEW_ROUND_REASON",
  });
});
it("release and owner cancel are explicit, once-only CAS commands", async () => {
  state.api.mockResolvedValue(task({ revision: 3 }));
  const view = render(
    <ReviewTaskDetail initialTask={activeTask()} zh={false} />,
  );
  fireEvent.click(actionConsent());
  fireEvent.click(screen.getByRole("button", { name: "Release claim" }));
  await waitFor(() => expect(writeCalls()).toHaveLength(1));
  view.unmount();
  state.api.mockReset();
  state.api.mockResolvedValue(ownerTask({ status: "cancelled", revision: 2 }));
  render(<ReviewTaskDetail initialTask={ownerTask()} zh={false} />);
  fireEvent.click(actionConsent());
  fireEvent.click(screen.getByRole("button", { name: "Cancel task grant" }));
  await screen.findByText(/Task action confirmed/);
  expect(writeCalls()[0]?.[0]).toContain("/cancel");
  expect(writeCalls()[0]?.[1]).toEqual({
    expected_revision: 1,
    confirmed: true,
  });
});

it("an evidence read completing after lease expiry cannot reopen sensitive content", async () => {
  rs.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
  const t = activeTask({
    assignment: {
      role: "reviewer_1",
      status: "active",
      lease_until_ms: Date.now() + 1000,
    },
  });
  let finish!: (value: unknown) => void;
  state.api.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  render(<ReviewTaskDetail initialTask={t} zh={false} />);
  fireEvent.click(
    screen.getByRole("button", {
      name: "Explicitly open input, output & reference",
    }),
  );
  act(() => {
    rs.advanceTimersByTime(1002);
  });
  await act(async () => {
    finish(taskCase(t));
  });
  expect(screen.queryByText("SYNTHETIC_GOLD")).toBeNull();
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(writeCalls()).toHaveLength(0);
});
