import { beforeEach, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  createPerformanceEvidenceAccess,
  listPerformanceDispatches,
  listPerformanceRuns,
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
