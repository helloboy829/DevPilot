import { beforeEach, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import { evaluationApi } from "@/core/evaluation/api";

const mockedFetch = rs.mocked(fetcher);
beforeEach(() => {
  mockedFetch.mockReset();
});
it("uses the authenticated fetcher, no-store, and explicit methods", async () => {
  mockedFetch.mockImplementation(
    async () => new Response(JSON.stringify({ revision: 0 })),
  );
  await evaluationApi("model-management");
  expect(mockedFetch.mock.calls[0]?.[1]).toMatchObject({
    method: "GET",
    cache: "no-store",
  });
  await evaluationApi(
    "model-management/roles",
    { roles: { general_agent: "synthetic" }, revision: 0 },
    "PUT",
  );
  expect(mockedFetch.mock.calls[1]?.[1]).toMatchObject({
    method: "PUT",
    cache: "no-store",
    body: JSON.stringify({
      roles: { general_agent: "synthetic" },
      revision: 0,
    }),
  });
  await evaluationApi(
    "model-management/models/synthetic?revision=1",
    undefined,
    "DELETE",
  );
  expect(mockedFetch.mock.calls[2]?.[1]).toMatchObject({ method: "DELETE" });
});
it("shows safe server errors rather than pretending to succeed", async () => {
  mockedFetch.mockResolvedValue(
    new Response(
      JSON.stringify({ detail: "Catalog changed; reload before saving" }),
      { status: 409 },
    ),
  );
  await expect(evaluationApi("model-management")).rejects.toThrow(
    "Catalog changed",
  );
});
