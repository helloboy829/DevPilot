import { beforeEach, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  createResponseEvidenceAccess,
  listResultRuns,
  readResponseEvidence,
} from "@/core/evaluation/results-api";

const mockedFetch = rs.mocked(fetcher);

beforeEach(() => {
  mockedFetch.mockReset();
});

it("lists runs with encoded project identity, filters and no-store", async () => {
  mockedFetch.mockResolvedValue(
    new Response(JSON.stringify({ items: [], next_cursor: null }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  await listResultRuns("p/1");
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/evaluation/projects/p%2F1/runs?limit=50",
    { method: "GET", cache: "no-store", headers: undefined },
  ]);
});

it("requests explicit response access against the implemented review-run contract", async () => {
  mockedFetch.mockResolvedValue(
    new Response(
      JSON.stringify({ access_id: "opaque", evidence_kind: "response" }),
      {
        headers: { "Content-Type": "application/json" },
      },
    ),
  );
  await createResponseEvidenceAccess("p1", "r1", 3, "a".repeat(64));
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/evaluation/projects/p1/review-runs/r1/cases/3/evidence-access",
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
});

it("reads only the opaque evidence access id and enforces a byte limit", async () => {
  mockedFetch.mockResolvedValue(
    new Response("response", {
      headers: { "Content-Type": "application/octet-stream" },
    }),
  );
  const bytes = await readResponseEvidence("p1", "opaque", 32);
  expect(new TextDecoder().decode(bytes)).toBe("response");
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/evaluation/projects/p1/evidence/opaque",
    { method: "GET", cache: "no-store", redirect: "error" },
  ]);
});

it("rejects oversized evidence, unexpected MIME and HTML without retry", async () => {
  mockedFetch.mockResolvedValue(
    new Response("x".repeat(33), {
      headers: { "Content-Type": "application/octet-stream" },
    }),
  );
  await expect(readResponseEvidence("p1", "opaque", 32)).rejects.toThrow();
  mockedFetch.mockResolvedValue(
    new Response("<html>login</html>", {
      headers: { "Content-Type": "text/html" },
    }),
  );
  await expect(readResponseEvidence("p1", "opaque", 32)).rejects.toThrow();
  expect(mockedFetch).toHaveBeenCalledTimes(2);
});

it("rejects partial-content evidence as an incomplete response", async () => {
  mockedFetch.mockResolvedValue(
    new Response("partial", {
      status: 206,
      headers: { "Content-Type": "application/octet-stream" },
    }),
  );
  await expect(readResponseEvidence("p1", "opaque", 32)).rejects.toThrow();
});
