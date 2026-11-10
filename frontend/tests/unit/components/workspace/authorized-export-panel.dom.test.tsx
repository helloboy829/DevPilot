import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { AuthorizedExportPanel } from "@/components/workspace/authorized-export-panel";
import type { PendingExports } from "@/core/evaluation/export-policy";

import {
  exportCapabilities,
  exportGrant,
  exportPlan,
  exportReceipt,
} from "../../../fixtures/authorized-export";
const state = rs.hoisted(() => ({ api: rs.fn(), bundle: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
rs.mock("@/core/evaluation/export-download", () => ({
  evaluationExportBundle: state.bundle,
}));
const writes = () =>
  state.api.mock.calls.filter((c: unknown[]) => c[2] === "PUT");
function response(route: string, _body?: unknown, _method?: string): unknown {
  if (route.endsWith("/export-capabilities")) return exportCapabilities;
  if (route.includes("/plans/")) return exportPlan;
  if (route.includes("/audit?"))
    return { events: [], next_after_sequence: null };
  if (route.includes("/exports/"))
    return exportReceipt(route.split("/").at(-1));
  throw Error("Unexpected API route");
}
beforeEach(() => {
  state.api.mockReset();
  state.bundle.mockReset();
  state.api.mockImplementation(response);
});
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});
const click = async (name: string) =>
  act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
function mount(
  pending: PendingExports = new Map(),
  projectId = "p1",
  writeLock = { current: false },
) {
  return {
    pending,
    writeLock,
    ...render(
      <AuthorizedExportPanel
        key={projectId}
        projectId={projectId}
        zh={false}
        pendingExports={pending}
        writeLock={writeLock}
      />,
    ),
  };
}
async function prepare() {
  await click("Load export policy and grants");
  fireEvent.change(screen.getByLabelText("Exact export grant"), {
    target: { value: exportGrant.id },
  });
  await click("Open selected frozen plan");
}
function consent() {
  for (const label of [
    "I confirm this exact source, grant, recipient and tier.",
    "I separately authorize the selected data to leave the platform.",
    "I acknowledge external destination, load, output protection and retention controls remain separate responsibilities.",
  ])
    fireEvent.click(screen.getByLabelText(label));
}
async function archive() {
  await prepare();
  consent();
  await click("Create authorized configuration archive");
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (e: Error) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}

it("loads nothing automatically and requires all three distinct consents after exact source open", async () => {
  const { pending } = mount();
  expect(state.api).not.toHaveBeenCalled();
  await prepare();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Create authorized configuration archive",
    }).disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByLabelText(
      "I confirm this exact source, grant, recipient and tier.",
    ),
  );
  expect(writes()).toHaveLength(0);
  fireEvent.click(
    screen.getByLabelText(
      "I separately authorize the selected data to leave the platform.",
    ),
  );
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Create authorized configuration archive",
    }).disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByLabelText(
      "I acknowledge external destination, load, output protection and retention controls remain separate responsibilities.",
    ),
  );
  await act(async () => {
    const button = screen.getByRole("button", {
      name: "Create authorized configuration archive",
    });
    fireEvent.click(button);
    fireEvent.click(button);
  });
  expect(writes()).toHaveLength(1);
  expect(pending.size).toBe(0);
  expect(writes()[0]?.[1]).toEqual({
    plan_id: "plan1",
    plan_hash: exportGrant.plan_hash,
    grant_id: exportGrant.id,
    recipient_id: exportGrant.recipient_id,
    tier: "baseline_inputs",
    confirmed: true,
    data_use_confirmed: true,
    external_controls_acknowledged: true,
  });
  expect(
    screen.getByText("Historical configuration receipt — NOT_EVALUATED"),
  ).toBeTruthy();
  expect(state.bundle).not.toHaveBeenCalled();
  expect(
    state.api.mock.calls.every(
      (c: unknown[]) =>
        !/gold|samples|execute|debug|request-versions/.test(String(c[0])),
    ),
  ).toBe(true);
});
it("refresh and grant/source edits revoke every consent; no default grant/source selection", async () => {
  mount();
  await prepare();
  consent();
  await click("Load export policy and grants");
  expect(
    screen.getByLabelText<HTMLSelectElement>("Exact export grant").value,
  ).toBe("");
  expect(
    screen.getByLabelText<HTMLInputElement>(
      "I confirm this exact source, grant, recipient and tier.",
    ).checked,
  ).toBe(false);
  fireEvent.change(screen.getByLabelText("Exact export grant"), {
    target: { value: exportGrant.id },
  });
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Create authorized configuration archive",
    }).disabled,
  ).toBe(true);
  expect(writes()).toHaveLength(0);
});
it("rejects changed source metadata without consent, write or target/model access", async () => {
  state.api.mockImplementation((route: string) =>
    route.includes("/plans/")
      ? { ...exportPlan, definition_hash: "0".repeat(64) }
      : response(route),
  );
  mount();
  await prepare();
  consent();
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(writes()).toHaveLength(0);
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Create authorized configuration archive",
    }).disabled,
  ).toBe(true);
});
it("keeps an unknown PUT ID across project switches and GET 404; only same-ID GET can reconcile", async () => {
  let missing = true;
  state.api.mockImplementation(
    (route: string, body?: unknown, method?: string) => {
      if (method === "PUT") return Promise.reject(Error("unknown delivery"));
      if (route.includes("/exports/") && missing)
        return Promise.reject(Error("404"));
      return response(route, body, method);
    },
  );
  const view = mount();
  await archive();
  const remembered = view.pending.get("p1")!;
  expect(remembered).toBeTruthy();
  await click("Reconcile the same export ID");
  expect(view.pending.get("p1")).toBe(remembered);
  view.rerender(
    <AuthorizedExportPanel
      key="p2"
      projectId="p2"
      zh={false}
      pendingExports={view.pending}
      writeLock={view.writeLock}
    />,
  );
  expect(screen.queryByText(remembered.id)).toBeNull();
  view.rerender(
    <AuthorizedExportPanel
      key="p1"
      projectId="p1"
      zh={false}
      pendingExports={view.pending}
      writeLock={view.writeLock}
    />,
  );
  expect(screen.getByText(remembered.id)).toBeTruthy();
  missing = false;
  await click("Reconcile the same export ID");
  expect(view.pending.size).toBe(0);
  expect(writes()).toHaveLength(1);
  const reads = state.api.mock.calls.filter(
    (c: unknown[]) => String(c[0]).includes("/exports/") && c[2] !== "PUT",
  );
  expect(
    reads.every((c: unknown[]) => String(c[0]).endsWith(remembered.id)),
  ).toBe(true);
});
it("late successful PUT cannot clear page-memory pending state or open a receipt in another project", async () => {
  const send = deferred<unknown>();
  state.api.mockImplementation(
    (route: string, body?: unknown, method?: string) =>
      method === "PUT" ? send.promise : response(route, body, method),
  );
  const view = mount();
  await archive();
  const remembered = view.pending.get("p1")!;
  expect(view.writeLock.current).toBe(true);
  view.rerender(
    <AuthorizedExportPanel
      key="p2"
      projectId="p2"
      zh={false}
      pendingExports={view.pending}
      writeLock={view.writeLock}
    />,
  );
  await act(async () => {
    send.resolve(exportReceipt(remembered.id));
    await send.promise;
  });
  expect(view.pending.get("p1")).toBe(remembered);
  expect(view.writeLock.current).toBe(false);
  expect(
    screen.queryByText("Historical configuration receipt — NOT_EVALUATED"),
  ).toBeNull();
});
it("malformed or mismatched successful receipt never clears pending or grants download", async () => {
  state.api.mockImplementation(
    (route: string, body?: unknown, method?: string) =>
      method === "PUT"
        ? { ...exportReceipt(route.split("/").at(-1)), all_frozen_samples: 1 }
        : response(route, body, method),
  );
  const view = mount();
  await archive();
  expect(view.pending.size).toBe(1);
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Download viewed configuration ZIP" }),
  ).toBeNull();
  expect(writes()).toHaveLength(1);
});
it("disabled policy does not prevent explicit historical reads, but never enables download or execution", async () => {
  state.api.mockImplementation((route: string) =>
    route.endsWith("/export-capabilities")
      ? {
          ...exportCapabilities,
          enabled: false,
          software_archive_sha256: null,
          grants: [],
        }
      : response(route),
  );
  mount();
  await click("Load export policy and grants");
  fireEvent.change(screen.getByLabelText("Historical export ID"), {
    target: { value: "d".repeat(32) },
  });
  await click("Open exact export receipt");
  expect(
    screen.getByText("Historical configuration receipt — NOT_EVALUATED"),
  ).toBeTruthy();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Download viewed configuration ZIP",
    }).disabled,
  ).toBe(true);
  expect(writes()).toHaveLength(0);
  expect(state.bundle).not.toHaveBeenCalled();
});
it("checks grant expiry again at click time rather than trusting prior consent", async () => {
  mount();
  await prepare();
  consent();
  rs.spyOn(Date, "now").mockReturnValue(exportGrant.expires_at_ms);
  await click("Create authorized configuration archive");
  expect(writes()).toHaveLength(0);
});
it("requires separate download confirmation and fences late binary responses after scope change", async () => {
  const result = deferred<Blob>();
  state.bundle.mockReturnValue(result.promise);
  const createUrl = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:synthetic");
  const view = mount();
  await archive();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Download viewed configuration ZIP",
    }).disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByLabelText(
      "I confirm downloading this viewed configuration to my device for the declared recipient.",
    ),
  );
  await click("Download viewed configuration ZIP");
  view.rerender(
    <AuthorizedExportPanel
      key="p2"
      projectId="p2"
      zh={false}
      pendingExports={view.pending}
      writeLock={view.writeLock}
    />,
  );
  await act(async () => {
    result.resolve(new Blob([new Uint8Array([80, 75, 3, 4])]));
    await result.promise;
  });
  expect(createUrl).not.toHaveBeenCalled();
  expect(state.bundle).toHaveBeenCalledTimes(1);
});
it("failed download revokes consent, does not create a file or retry", async () => {
  state.bundle.mockRejectedValue(Error("corrupt binary"));
  const createUrl = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:synthetic");
  mount();
  await archive();
  fireEvent.click(
    screen.getByLabelText(
      "I confirm downloading this viewed configuration to my device for the declared recipient.",
    ),
  );
  await click("Download viewed configuration ZIP");
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(createUrl).not.toHaveBeenCalled();
  expect(state.bundle).toHaveBeenCalledTimes(1);
  expect(
    screen.getByLabelText<HTMLInputElement>(
      "I confirm downloading this viewed configuration to my device for the declared recipient.",
    ).checked,
  ).toBe(false);
});
it("opens only an explicit historical ID and manually loads a validated ordered audit", async () => {
  const receipt = exportReceipt();
  state.api.mockImplementation((route: string) =>
    route.includes("/audit?")
      ? {
          events: [
            {
              id: "5".repeat(32),
              project_id: "p1",
              export_id: receipt.id,
              actor: exportGrant.owner_id,
              action: "export_created",
              sequence: 1,
              at_ms: 20000,
            },
          ],
          next_after_sequence: null,
        }
      : response(route),
  );
  mount();
  fireEvent.change(screen.getByLabelText("Historical export ID"), {
    target: { value: receipt.id },
  });
  expect(state.api).not.toHaveBeenCalled();
  await click("Open exact export receipt");
  await click("Load export audit");
  expect(screen.getByText("1 · export_created · 20000")).toBeTruthy();
  expect(writes()).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("Historical export ID"), {
    target: { value: "a".repeat(32) },
  });
  expect(
    screen.queryByText("Historical configuration receipt — NOT_EVALUATED"),
  ).toBeNull();
});

it("rechecks download expiry both before GET and after awaiting the binary", async () => {
  const result = deferred<Blob>();
  state.bundle.mockReturnValue(result.promise);
  const createUrl = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:synthetic");
  mount();
  await archive();
  fireEvent.click(
    screen.getByLabelText(
      "I confirm downloading this viewed configuration to my device for the declared recipient.",
    ),
  );
  await click("Download viewed configuration ZIP");
  rs.spyOn(Date, "now").mockReturnValue(exportGrant.expires_at_ms);
  await act(async () => {
    result.resolve(new Blob([new Uint8Array([80, 75, 3, 4])]));
    await result.promise;
  });
  expect(createUrl).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(state.bundle).toHaveBeenCalledTimes(1);
});
