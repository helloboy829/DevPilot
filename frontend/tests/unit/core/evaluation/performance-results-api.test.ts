import { beforeEach, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  createPerformanceEvidenceAccess,
  createPerformanceRun,
  createPerformanceScenario,
  getPerformanceMetrics,
  listPerformanceDispatches,
  listPerformanceRuns,
  listPerformanceScenarios,
  readPerformanceEvidence,
} from "@/core/evaluation/performance-results-api";

const mockedFetch = rs.mocked(fetcher);

beforeEach(() => {
  mockedFetch.mockReset();
});

it("uses stable cursor pages for owner-scoped performance run metadata", async () => {
  mockedFetch.mockResolvedValue(
    new Response(JSON.stringify({ items: [], total: 0, next_cursor: null }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  await listPerformanceRuns("p/1", { limit: 25, cursor: "opaque cursor" });
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/evaluation/projects/p%2F1/performance-runs?limit=25&cursor=opaque+cursor",
    { method: "GET", cache: "no-store", headers: undefined },
  ]);
});

it("reads dispatch metadata without implicitly opening response evidence", async () => {
  mockedFetch.mockResolvedValue(
    new Response(JSON.stringify({ dispatches: [], offset: 0, limit: 100 }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  await listPerformanceDispatches("p1", "r/1");
  expect(mockedFetch.mock.calls[0]?.[0]).toBe(
    "/backend/api/evaluation/projects/p1/performance-runs/r%2F1/dispatches?offset=0&limit=100",
  );
  expect(mockedFetch).toHaveBeenCalledTimes(1);
});

it("requires a one-time explicit evidence grant before reading response bytes", async () => {
  mockedFetch.mockResolvedValueOnce(
    new Response(JSON.stringify({ access_id: "opaque", expires_at_ms: 1 }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  await createPerformanceEvidenceAccess("p1", "r1", 2, "a".repeat(64));
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/evaluation/projects/p1/performance-runs/r1/dispatches/2/evidence-access",
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: "response",
        evidence_hash: "a".repeat(64),
        confirmed: true,
      }),
    },
  ]);

  mockedFetch.mockResolvedValueOnce(
    new Response("private response", {
      headers: { "Content-Type": "application/octet-stream" },
    }),
  );
  const bytes = await readPerformanceEvidence("p1", "opaque", 64);
  expect(new TextDecoder().decode(bytes)).toBe("private response");
  expect(mockedFetch.mock.calls[1]).toEqual([
    "/backend/api/evaluation/projects/p1/performance-evidence/opaque",
    { method: "GET", cache: "no-store", redirect: "error" },
  ]);
});

it("rejects oversized and non-binary evidence without retry", async () => {
  mockedFetch.mockResolvedValue(
    new Response("x".repeat(33), {
      headers: { "Content-Type": "application/octet-stream" },
    }),
  );
  await expect(readPerformanceEvidence("p1", "opaque", 32)).rejects.toThrow();
  expect(mockedFetch).toHaveBeenCalledTimes(1);
});

it("loads the versioned metrics projection independently from run metadata", async () => {
  mockedFetch.mockResolvedValue(
    new Response(
      JSON.stringify({
        schema_version: "performance-metrics.v1",
        applicability: "not_measured",
        revision: null,
        metrics: null,
      }),
      { headers: { "Content-Type": "application/json" } },
    ),
  );
  await getPerformanceMetrics("p/1", "r/1");
  expect(mockedFetch.mock.calls[0]?.[0]).toBe(
    "/backend/api/evaluation/projects/p%2F1/performance-runs/r%2F1/metrics",
  );
  expect(mockedFetch.mock.calls[0]?.[1]).toMatchObject({
    method: "GET",
    cache: "no-store",
  });
});

it("lists component performance scenarios without caching", async () => {
  mockedFetch.mockResolvedValue(
    new Response(JSON.stringify({ scenarios: [] }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  await listPerformanceScenarios("p/1", "component 1");
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/evaluation/projects/p%2F1/components/component%201/performance-scenarios",
    { method: "GET", cache: "no-store", headers: undefined },
  ]);
});

it("creates a frozen scenario with the explicit confirmation payload", async () => {
  const payload = {
    plan_id: "plan_1",
    profile: {
      concurrency: 1,
      measured_request_count: 4,
      warmup_request_count: 0,
      duration_limit_seconds: null,
      request_timeout_ms: 1000,
      max_in_flight: 1,
      wall_time_limit_seconds: 10,
      drain_limit_seconds: 1,
      max_request_bytes: 1024,
      max_response_bytes: 1024,
      max_total_bytes: 2048,
    },
    confirmed: true as const,
  };
  mockedFetch.mockResolvedValue(
    new Response(JSON.stringify({ id: "scenario1" }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  await createPerformanceScenario("p/1", "c/1", payload);
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/evaluation/projects/p%2F1/components/c%2F1/performance-scenarios",
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  ]);
});

it("creates a run ledger once with the exact caller-provided run ID", async () => {
  const payload = {
    run_id: "a".repeat(32),
    scenario_id: "scenario_1",
    scenario_hash: "b".repeat(64),
    confirmed: true as const,
  };
  mockedFetch.mockResolvedValue(
    new Response(JSON.stringify({ id: payload.run_id }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  await createPerformanceRun("p/1", payload);
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/evaluation/projects/p%2F1/performance-runs",
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  ]);
  expect(mockedFetch).toHaveBeenCalledTimes(1);
});
