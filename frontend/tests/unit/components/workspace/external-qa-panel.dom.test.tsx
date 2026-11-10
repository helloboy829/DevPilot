import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ExternalQAPanel } from "@/components/workspace/external-qa-panel";
import type { PendingIntakes } from "@/core/evaluation/external-qa-policy";

import fixture from "../../../fixtures/synthetic-external-qa.json";
const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/external-qa-api", () => ({
  externalQAApi: state.api,
}));
const project = fixture.receipt.project_id;
const writeCalls = () =>
  state.api.mock.calls.filter((c: unknown[]) => c[1] !== undefined);
const labels = [
  "I confirm the exact historical export and original run ID.",
  "I confirm these two files contain technical metadata only, not outputs, QA, keys or journals.",
  "I acknowledge this untrusted declaration is not evidence, approval or execution authority.",
];
const file = (raw: string) => {
  const data = new TextEncoder().encode(raw);
  return { size: data.byteLength, arrayBuffer: async () => data.buffer };
};
function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (e: Error) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  state.api.mockReset();
  state.api.mockImplementation(async (route: string, _body?: unknown) => {
    if (route.includes("/exports/")) return fixture.export_receipt;
    if (route.includes("/plans/")) return fixture.plan;
    if (route.includes("/audit?"))
      return { events: [], next_after_sequence: null };
    if (route.includes("/external-qa-intakes/")) return fixture.receipt;
    throw Error("Unexpected metadata API");
  });
  rs.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
    "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
  );
});
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});
function mount(
  pending: PendingIntakes = new Map(),
  projectId = project,
  writeLock = { current: false },
  zh = false,
) {
  return {
    pending,
    writeLock,
    ...render(
      <ExternalQAPanel
        key={projectId + String(zh)}
        projectId={projectId}
        zh={zh}
        pendingIntakes={pending}
        writeLock={writeLock}
      />,
    ),
  };
}
const click = async (name: string) =>
  act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
async function source() {
  fireEvent.change(screen.getByLabelText("Exact historical export ID"), {
    target: { value: fixture.export_receipt.id },
  });
  await click("Open historical export and frozen plan");
  await waitFor(() =>
    expect(screen.getByText("Historical baseline source opened")).toBeTruthy(),
  );
}
async function prepare() {
  await source();
  fireEvent.change(screen.getByLabelText("Original external run UUID"), {
    target: { value: fixture.request.original_run_id },
  });
  fireEvent.change(screen.getByLabelText("Receipt JSON file"), {
    target: { files: [file(fixture.request.receipt_json)] },
  });
  fireEvent.change(screen.getByLabelText("Reconciliation JSON file"), {
    target: { files: [file(fixture.request.reconciliation_json)] },
  });
  await waitFor(() =>
    expect(
      screen.getByText(fixture.request.reconciliation_sha256, { exact: false }),
    ).toBeTruthy(),
  );
  await click("Inspect selected technical documents");
  await waitFor(() =>
    expect(
      screen.getByText("Technical inspection only — NOT_EVALUATED"),
    ).toBeTruthy(),
  );
}
function consent() {
  for (const label of labels) fireEvent.click(screen.getByLabelText(label));
}
async function archive() {
  await prepare();
  consent();
  await click("Quarantine technical declarations");
}
it("has no automatic reads or writes and requires all three independent consents", async () => {
  mount();
  expect(state.api).not.toHaveBeenCalled();
  await prepare();
  expect(state.api.mock.calls.map((c) => c[0])).toEqual([
    expect.stringContaining("/exports/"),
    expect.stringContaining("/plans/"),
  ]);
  for (const label of labels) {
    expect(
      screen.getByRole<HTMLButtonElement>("button", {
        name: "Quarantine technical declarations",
      }).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByLabelText(label));
  }
  await click("Quarantine technical declarations");
  await waitFor(() =>
    expect(
      screen.getByText("Historical quarantine receipt — NOT_EVALUATED"),
    ).toBeTruthy(),
  );
  expect(writeCalls()).toHaveLength(1);
  expect(writeCalls()[0]?.[1]).toEqual(fixture.request);
});
it("edits revoke confirmation and invalidate inspected documents without sends", async () => {
  mount();
  await prepare();
  consent();
  fireEvent.change(screen.getByLabelText("Original external run UUID"), {
    target: { value: "00000000-0000-0000-0000-000000000005" },
  });
  expect(
    screen.queryByText("Technical inspection only — NOT_EVALUATED"),
  ).toBeNull();
  for (const label of labels)
    expect(screen.getByLabelText<HTMLInputElement>(label).checked).toBe(false);
  expect(writeCalls()).toHaveLength(0);
});
it("registers only safe expected metadata before PUT and fences double clicks", async () => {
  const pending: PendingIntakes = new Map();
  const put = deferred<unknown>();
  state.api.mockImplementation(async (route: string, body?: unknown) =>
    body
      ? put.promise
      : route.includes("/exports/")
        ? fixture.export_receipt
        : fixture.plan,
  );
  const { writeLock } = mount(pending);
  await prepare();
  consent();
  await click("Quarantine technical declarations");
  await click("Quarantine technical declarations");
  expect(writeCalls()).toHaveLength(1);
  expect(pending.get(project)?.id).toBe(fixture.receipt.id);
  expect(writeLock.current).toBe(true);
  expect(JSON.stringify([...pending.values()])).not.toContain("receipt_json");
  expect(JSON.stringify([...pending.values()])).not.toContain(
    "reconciliation_json",
  );
  await act(async () => put.resolve(fixture.receipt));
  await waitFor(() => expect(pending.size).toBe(0));
  expect(writeLock.current).toBe(false);
});
it("lost acknowledgement and GET404 preserve same ID; only explicit same-ID GET can reconcile", async () => {
  const pending: PendingIntakes = new Map();
  let reads = 0;
  state.api.mockImplementation(async (route: string, body?: unknown) => {
    if (body) throw Error("private error");
    if (route.includes("/external-qa-intakes/")) {
      if (++reads === 1) throw Error("404");
      return fixture.receipt;
    }
    return route.includes("/exports/") ? fixture.export_receipt : fixture.plan;
  });
  mount(pending);
  await archive();
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  expect(pending.get(project)?.id).toBe(fixture.receipt.id);
  await click("Reconcile same intake ID by GET");
  await waitFor(() => expect(reads).toBe(1));
  expect(pending.size).toBe(1);
  await click("Reconcile same intake ID by GET");
  await waitFor(() => expect(pending.size).toBe(0));
  expect(writeCalls()).toHaveLength(1);
  expect(
    state.api.mock.calls
      .filter((c) => String(c[0]).includes("/external-qa-intakes/"))
      .map((c) => c[0]),
  ).toEqual(
    Array(3).fill(
      "evaluation/projects/" +
        project +
        "/external-qa-intakes/" +
        fixture.receipt.id,
    ),
  );
  expect(screen.queryByText("private error")).toBeNull();
});
it("malformed success never clears pending or upgrades authority", async () => {
  const pending: PendingIntakes = new Map();
  state.api.mockImplementation(async (route: string, body?: unknown) =>
    body
      ? { ...fixture.receipt, approval_granted: true }
      : route.includes("/exports/")
        ? fixture.export_receipt
        : fixture.plan,
  );
  mount(pending);
  await archive();
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  expect(pending.size).toBe(1);
  expect(
    screen.queryByText("Historical quarantine receipt — NOT_EVALUATED"),
  ).toBeNull();
});
it("late PUT after project switch cannot open old data or clear parent pending; global write lock survives", async () => {
  const pending: PendingIntakes = new Map(),
    writeLock = { current: false },
    put = deferred<unknown>();
  state.api.mockImplementation(async (route: string, body?: unknown) =>
    body
      ? put.promise
      : route.includes("/exports/")
        ? fixture.export_receipt
        : fixture.plan,
  );
  const view = mount(pending, project, writeLock);
  await prepare();
  consent();
  await click("Quarantine technical declarations");
  view.rerender(
    <ExternalQAPanel
      key="other"
      projectId="other"
      zh={false}
      pendingIntakes={pending}
      writeLock={writeLock}
    />,
  );
  expect(writeLock.current).toBe(true);
  await act(async () => put.resolve(fixture.receipt));
  expect(pending.size).toBe(1);
  await waitFor(() => expect(writeLock.current).toBe(false));
  expect(
    screen.queryByText("Historical quarantine receipt — NOT_EVALUATED"),
  ).toBeNull();
  view.rerender(
    <ExternalQAPanel
      key="back"
      projectId={project}
      zh={false}
      pendingIntakes={pending}
      writeLock={writeLock}
    />,
  );
  expect(screen.getByRole("status").textContent).toContain(fixture.receipt.id);
  expect(writeCalls()).toHaveLength(1);
});
it("late historical source response after unmount never starts a plan read", async () => {
  const response = deferred<unknown>();
  state.api.mockReturnValue(response.promise);
  const view = mount();
  fireEvent.change(screen.getByLabelText("Exact historical export ID"), {
    target: { value: fixture.export_receipt.id },
  });
  await click("Open historical export and frozen plan");
  view.unmount();
  await act(async () => response.resolve(fixture.export_receipt));
  expect(state.api).toHaveBeenCalledTimes(1);
});
it("late file reads cannot restore replaced documents or confirmation", async () => {
  const read = deferred<ArrayBuffer>();
  mount();
  await source();
  fireEvent.change(screen.getByLabelText("Receipt JSON file"), {
    target: { files: [{ size: 1, arrayBuffer: () => read.promise }] },
  });
  fireEvent.change(screen.getByLabelText("Receipt JSON file"), {
    target: { files: [file(fixture.request.receipt_json)] },
  });
  await waitFor(() =>
    expect(
      screen.getByText(fixture.request.receipt_sha256, { exact: false }),
    ).toBeTruthy(),
  );
  await act(async () => read.resolve(new TextEncoder().encode("x").buffer));
  expect(
    screen.getByText(fixture.request.receipt_sha256, { exact: false }),
  ).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});
it("oversized files are rejected before reading, with generic errors and no writes", async () => {
  mount();
  await source();
  const read = rs.fn();
  fireEvent.change(screen.getByLabelText("Receipt JSON file"), {
    target: { files: [{ size: 8193, arrayBuffer: read }] },
  });
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  expect(read).not.toHaveBeenCalled();
  expect(writeCalls()).toHaveLength(0);
});
it("historical intake and audit are explicit literal metadata reads without current export grants", async () => {
  mount();
  fireEvent.change(screen.getByLabelText("Exact historical intake ID"), {
    target: { value: fixture.receipt.id },
  });
  await click("Open historical quarantine receipt");
  await waitFor(() =>
    expect(
      screen.getByText("Historical quarantine receipt — NOT_EVALUATED"),
    ).toBeTruthy(),
  );
  await click("Load quarantine audit");
  expect(state.api.mock.calls.map((c) => c[0])).toEqual([
    "evaluation/projects/" +
      project +
      "/external-qa-intakes/" +
      fixture.receipt.id,
    "evaluation/projects/" +
      project +
      "/external-qa-intakes/" +
      fixture.receipt.id +
      "/audit?after_sequence=0&limit=50",
  ]);
  expect(writeCalls()).toHaveLength(0);
  expect(document.querySelector("iframe")).toBeNull();
});
it("locale remount retains the original pending ID without automatic reconciliation", async () => {
  const pending: PendingIntakes = new Map();
  state.api.mockImplementation(async (route: string, body?: unknown) => {
    if (body) throw Error("lost");
    return route.includes("/exports/") ? fixture.export_receipt : fixture.plan;
  });
  const view = mount(pending);
  await archive();
  await waitFor(() => expect(pending.size).toBe(1));
  const count = state.api.mock.calls.length;
  view.rerender(
    <ExternalQAPanel
      key="zh"
      projectId={project}
      zh
      pendingIntakes={pending}
      writeLock={{ current: false }}
    />,
  );
  expect(screen.getByRole("status").textContent).toContain(fixture.receipt.id);
  expect(state.api).toHaveBeenCalledTimes(count);
});

it("parent write lock blocks a second project even with a fully prepared form", async () => {
  const writeLock = { current: true };
  mount(new Map(), project, writeLock);
  await prepare();
  consent();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Quarantine technical declarations",
    }).disabled,
  ).toBe(true);
  expect(writeCalls()).toHaveLength(0);
});
it.each([
  "Original external run UUID",
  "Exact historical export ID",
  "Exact historical intake ID",
])("editing %s revokes all creation consents", async (label) => {
  mount();
  await prepare();
  consent();
  fireEvent.change(screen.getByLabelText(label), {
    target: { value: "changed" },
  });
  expect(
    screen.getAllByRole<HTMLInputElement>("checkbox").every((e) => !e.checked),
  ).toBe(true);
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Quarantine technical declarations",
    }).disabled,
  ).toBe(true);
  expect(writeCalls()).toHaveLength(0);
});
it("a changed file invalidates inspection and all confirmations", async () => {
  mount();
  await prepare();
  consent();
  fireEvent.change(screen.getByLabelText("Receipt JSON file"), {
    target: { files: [file(fixture.request.receipt_json)] },
  });
  await waitFor(() =>
    expect(
      screen.getByText(fixture.request.receipt_sha256, { exact: false }),
    ).toBeTruthy(),
  );
  expect(
    screen.queryByText("Technical inspection only — NOT_EVALUATED"),
  ).toBeNull();
  expect(
    screen.getAllByRole<HTMLInputElement>("checkbox").every((e) => !e.checked),
  ).toBe(true);
  expect(writeCalls()).toHaveLength(0);
});
it("an unmounted file read cannot restore data after remount", async () => {
  const read = deferred<ArrayBuffer>(),
    view = mount();
  await source();
  fireEvent.change(screen.getByLabelText("Receipt JSON file"), {
    target: { files: [{ size: 1, arrayBuffer: () => read.promise }] },
  });
  view.rerender(
    <ExternalQAPanel
      key="new"
      projectId="other"
      zh={false}
      pendingIntakes={new Map()}
      writeLock={{ current: false }}
    />,
  );
  await act(async () => read.resolve(new TextEncoder().encode("x").buffer));
  expect(screen.queryByRole("alert")).toBeNull();
  expect(
    screen.queryByText("Technical inspection only — NOT_EVALUATED"),
  ).toBeNull();
  expect(writeCalls()).toHaveLength(0);
});
it("malformed same-ID GET retains pending and never resends or opens a receipt", async () => {
  const pending: PendingIntakes = new Map();
  state.api.mockImplementation(async (route: string, body?: unknown) => {
    if (body) throw Error("lost acknowledgement");
    if (route.includes("/exports/")) return fixture.export_receipt;
    if (route.includes("/plans/")) return fixture.plan;
    return { ...fixture.receipt, archive_hash: "0".repeat(64) };
  });
  mount(pending);
  await archive();
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  await click("Reconcile same intake ID by GET");
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  expect(pending.size).toBe(1);
  expect(writeCalls()).toHaveLength(1);
  expect(
    screen.queryByText("Historical quarantine receipt — NOT_EVALUATED"),
  ).toBeNull();
  expect(state.api.mock.calls.at(-1)?.[0]).toBe(
    "evaluation/projects/" +
      project +
      "/external-qa-intakes/" +
      fixture.receipt.id,
  );
});
it("bad audit cursor is rejected without installing events or next-page controls", async () => {
  mount();
  fireEvent.change(screen.getByLabelText("Exact historical intake ID"), {
    target: { value: fixture.receipt.id },
  });
  await click("Open historical quarantine receipt");
  await waitFor(() =>
    expect(
      screen.getByText("Historical quarantine receipt — NOT_EVALUATED"),
    ).toBeTruthy(),
  );
  state.api.mockResolvedValue({ events: [], next_after_sequence: 1 });
  await click("Load quarantine audit");
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  expect(
    screen.queryByRole("button", { name: "Load next quarantine audit page" }),
  ).toBeNull();
  expect(writeCalls()).toHaveLength(0);
});
