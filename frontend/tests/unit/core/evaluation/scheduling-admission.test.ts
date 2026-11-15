import { beforeEach, expect, it, rs } from "@rstest/core";

import {
  loadSchedulingAdmission,
  parseSchedulingAdmission,
} from "@/core/evaluation/scheduling-admission";

import admission from "../../../fixtures/scheduling-admission";

const state = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: state.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));
beforeEach(() => state.fetch.mockReset());

const load = () => loadSchedulingAdmission(new AbortController().signal);
const response = (data: unknown = admission, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });

it("accepts the fixed denial projection", () => {
  expect(parseSchedulingAdmission(admission)).toEqual(admission);
});

it.each([
  ["schema", "qa-scheduling-admission.v2"],
  ["scope", "other"],
  ["scheduler_scope", "qa_chain"],
  ["qa_chain_admitted", true],
  ["dispatch_authorized", true],
  ["release_authorized", true],
  ["blockers", ["unknown_blocker"]],
  [
    "blockers",
    ["worker_liveness_not_established", "worker_liveness_not_established"],
  ],
  ["blockers", "no_versioned_admission_contract"],
  ["owner_id", "SECRET-SENTINEL"],
  ["blockers_extra", []],
])("rejects wrong %s without reflecting values", (field, value) => {
  expect(() =>
    parseSchedulingAdmission({ ...admission, [field]: value }),
  ).toThrow("Scheduling admission diagnostics unavailable");
});

it("uses the authenticated fetcher with GET/no-store and the exact caller signal, once", async () => {
  state.fetch.mockResolvedValue(response());
  const controller = new AbortController();
  expect(await loadSchedulingAdmission(controller.signal)).toEqual(admission);
  expect(state.fetch.mock.calls).toEqual([
    [
      "/backend/api/evaluation/operations/scheduling-admission",
      { method: "GET", cache: "no-store", signal: controller.signal },
    ],
  ]);
});

it.each([401, 403, 404, 503])(
  "does not read or echo an error body or retry HTTP %s",
  async (status) => {
    const cancel = rs.fn(async () => undefined);
    const read = rs.fn();
    state.fetch.mockResolvedValue({
      ok: false,
      status,
      body: { cancel },
      json: read,
      text: read,
    });
    await expect(load()).rejects.toThrow(
      "Scheduling admission diagnostics unavailable",
    );
    expect(read).not.toHaveBeenCalled();
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(state.fetch).toHaveBeenCalledTimes(1);
  },
);

it.each([
  ["Content-Type", "text/html"],
  ["Content-Length", "16385"],
  ["Content-Length", "garbage"],
])("rejects MIME or declared bounds", async (name, value) => {
  state.fetch.mockResolvedValue(response(admission, { [name]: value }));
  await expect(load()).rejects.toThrow(
    "Scheduling admission diagnostics unavailable",
  );
  expect(state.fetch).toHaveBeenCalledTimes(1);
});

it.each([
  new Uint8Array([0xff]),
  new TextEncoder().encode("SECRET-SENTINEL not JSON"),
])("rejects malformed UTF8 or invalid JSON without retry", async (bytes) => {
  state.fetch.mockResolvedValue(
    new Response(bytes, {
      headers: { "Content-Type": "application/json" },
    }),
  );
  await expect(load()).rejects.toThrow(
    "Scheduling admission diagnostics unavailable",
  );
  expect(state.fetch).toHaveBeenCalledTimes(1);
});

it("suppresses network errors without automatic retry", async () => {
  state.fetch.mockRejectedValue(new Error("SECRET-SENTINEL"));
  await expect(load()).rejects.toThrow(
    /^Scheduling admission diagnostics unavailable$/,
  );
  expect(state.fetch).toHaveBeenCalledTimes(1);
  // A later explicit manual read is allowed; the failed call is never retried.
  state.fetch.mockResolvedValue(response());
  expect(await load()).toEqual(admission);
  expect(state.fetch).toHaveBeenCalledTimes(2);
});

it("rejects a result after the caller aborts", async () => {
  state.fetch.mockResolvedValue(response());
  const controller = new AbortController();
  controller.abort();
  await expect(loadSchedulingAdmission(controller.signal)).rejects.toThrow(
    /^Scheduling admission diagnostics unavailable$/,
  );
});
