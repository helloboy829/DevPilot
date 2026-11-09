import { beforeEach, expect, it, rs } from "@rstest/core";

import {
  loadReservationSnapshot,
  parseReservationSnapshot,
} from "@/core/evaluation/execution-operations";

import fixture from "../../../fixtures/reservation-snapshot";

const state = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: state.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));
beforeEach(() => state.fetch.mockReset());
const clone = () => structuredClone(fixture);
const load = () => loadReservationSnapshot(new AbortController().signal);
const response = (data: unknown = fixture, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
it("accepts coherent ALL-state counts above current process limits without inventing quota", () => {
  const result = parseReservationSnapshot(fixture);
  expect(result.reservations.held_runs).toBe(3);
  expect(result.reservations.reserved_concurrency).toBe(70);
  expect(result.policy.max_reserved_concurrency).toBe(8);
  expect(result.states.interrupted).toEqual({
    held_runs: 1,
    deadline_reached_runs: 1,
  });
  expect(result).toEqual(fixture);
});
it("accepts an empty held population and the exact policy boundaries", () => {
  const data = clone();
  for (const key of Object.keys(
    data.reservations,
  ) as (keyof typeof data.reservations)[])
    data.reservations[key] = 0;
  for (const item of Object.values(data.states)) {
    item.held_runs = 0;
    item.deadline_reached_runs = 0;
  }
  data.observed_at_ms = 0;
  Object.assign(data.policy, {
    max_active_runs: 32,
    max_reserved_concurrency: 64,
    max_response_bytes: 1048576,
    max_reserved_body_bytes: 1,
    max_reserved_response_bytes: 2,
  });
  expect(parseReservationSnapshot(data)).toEqual(data);
});
it.each([
  ["scope", "other"],
  ["policy_scope", "global"],
  ["worker_liveness", "dead"],
  ["release_authorized", true],
  ["reclaim_authorized", true],
  ["retry_authorized", true],
  ["dispatch_authorized", true],
  ["observed_at_ms", -1],
  ["observed_at_ms", 0.5],
  ["observed_at_ms", Number.MAX_SAFE_INTEGER + 1],
  ["owner_id", "SECRET-SENTINEL"],
])("rejects wrong top-level %s without reflecting values", (field, value) => {
  expect(() =>
    parseReservationSnapshot({ ...fixture, [field]: value }),
  ).toThrow("Reservation diagnostics unavailable");
});
it.each([
  { ...fixture.policy, max_active_runs: 33 },
  { ...fixture.policy, max_reserved_concurrency: 0 },
  { ...fixture.policy, max_response_bytes: 1048577 },
  { ...fixture.policy, max_reserved_body_bytes: 67108865 },
  { ...fixture.policy, max_reserved_response_bytes: 1 },
  { ...fixture.policy, enabled: "false" },
  { ...fixture.policy, token: "SECRET-SENTINEL" },
])("rejects invalid or extra policy fields", (policy) => {
  expect(() => parseReservationSnapshot({ ...fixture, policy })).toThrow(
    "Reservation diagnostics unavailable",
  );
});
it("rejects missing/extra states and incoherent totals or per-state deadlines", () => {
  const cases: unknown[] = [
    {
      ...fixture,
      states: {
        ...fixture.states,
        unknown: { held_runs: 0, deadline_reached_runs: 0 },
      },
    },
    { ...fixture, states: { ...fixture.states, queued: undefined } },
    { ...fixture, reservations: { ...fixture.reservations, held_runs: 2 } },
    {
      ...fixture,
      reservations: { ...fixture.reservations, deadline_reached_runs: 3 },
    },
    {
      ...fixture,
      states: {
        ...fixture.states,
        queued: { held_runs: 0, deadline_reached_runs: 1 },
      },
    },
    {
      ...fixture,
      states: {
        ...fixture.states,
        running: {
          held_runs: 1,
          deadline_reached_runs: 1,
          input: "SECRET-SENTINEL",
        },
      },
    },
  ];
  for (const value of cases)
    expect(() => parseReservationSnapshot(value)).toThrow(
      "Reservation diagnostics unavailable",
    );
});
it.each([-1, 0.5, "3", null, true, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])(
  "rejects non-safe reservation counts: %s",
  (value) => {
    expect(() =>
      parseReservationSnapshot({
        ...fixture,
        reservations: { ...fixture.reservations, reserved_concurrency: value },
      }),
    ).toThrow("Reservation diagnostics unavailable");
  },
);
it("uses the authenticated fetcher with GET/no-store and the exact caller signal, once", async () => {
  state.fetch.mockResolvedValue(response());
  const controller = new AbortController();
  expect(await loadReservationSnapshot(controller.signal)).toEqual(fixture);
  expect(state.fetch.mock.calls).toEqual([
    [
      "/backend/api/evaluation/operations/reservations",
      { method: "GET", cache: "no-store", signal: controller.signal },
    ],
  ]);
});
it.each([401, 403, 404, 409, 503])(
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
    await expect(load()).rejects.toThrow("Reservation diagnostics unavailable");
    expect(read).not.toHaveBeenCalled();
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(state.fetch).toHaveBeenCalledTimes(1);
  },
);
it.each([
  ["Content-Type", "text/html"],
  ["Content-Length", "16385"],
  ["Content-Length", "-1"],
  ["Content-Length", "garbage"],
])(
  "rejects MIME/declared bounds without parsing server details",
  async (name, value) => {
    state.fetch.mockResolvedValue(response(fixture, { [name]: value }));
    await expect(load()).rejects.toThrow("Reservation diagnostics unavailable");
    expect(state.fetch).toHaveBeenCalledTimes(1);
  },
);
it.each([
  new TextEncoder().encode(" ".repeat(16385)),
  new Uint8Array([0xff]),
  new TextEncoder().encode("SECRET-SENTINEL not JSON"),
])(
  "rejects actual stream overflow, malformed UTF8 and invalid JSON",
  async (bytes) => {
    state.fetch.mockResolvedValue(
      new Response(bytes, { headers: { "Content-Type": "application/json" } }),
    );
    await expect(load()).rejects.toThrow("Reservation diagnostics unavailable");
    expect(state.fetch).toHaveBeenCalledTimes(1);
  },
);
it("handles split UTF8 streams and cancels an oversized chunked response", async () => {
  const bytes = new TextEncoder().encode(JSON.stringify(fixture));
  state.fetch.mockResolvedValue(
    new Response(
      new ReadableStream({
        start(c) {
          c.enqueue(bytes.slice(0, 10));
          c.enqueue(bytes.slice(10));
          c.close();
        },
      }),
      { headers: { "Content-Type": "application/json" } },
    ),
  );
  expect(await load()).toEqual(fixture);
  const cancel = rs.fn();
  state.fetch.mockResolvedValue(
    new Response(
      new ReadableStream({
        pull(c) {
          c.enqueue(new Uint8Array(16385));
        },
        cancel,
      }),
      {
        headers: { "Content-Type": "application/json", "Content-Length": "1" },
      },
    ),
  );
  await expect(load()).rejects.toThrow("Reservation diagnostics unavailable");
  expect(cancel).toHaveBeenCalledTimes(1);
});
it("suppresses network/stream details and an aborted result, without retry", async () => {
  state.fetch.mockRejectedValue(new Error("SECRET-SENTINEL"));
  await expect(load()).rejects.toThrow(/^Reservation diagnostics unavailable$/);
  expect(state.fetch).toHaveBeenCalledTimes(1);
  state.fetch.mockResolvedValue(response());
  const controller = new AbortController();
  controller.abort();
  await expect(loadReservationSnapshot(controller.signal)).rejects.toThrow(
    /^Reservation diagnostics unavailable$/,
  );
});
