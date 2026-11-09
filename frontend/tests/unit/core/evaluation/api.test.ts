import { beforeEach, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  evaluationApi,
  evaluationReportDocx,
  evaluationIndependentReportDocx,
} from "@/core/evaluation/api";

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

const docxMime =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
it("downloads binary through authenticated no-store fetch without JSON conversion", async () => {
  mockedFetch.mockResolvedValue(
    new Response(new Uint8Array([80, 75, 3, 4]), {
      headers: {
        "Content-Type": docxMime,
        "X-DevPilot-Renderer": "qa-docx-v1",
      },
    }),
  );
  const result = await evaluationReportDocx(
    "evaluation/projects/p/report-archives/a/exports/qa-docx-v1?archive_hash=h",
  );
  expect(result.type).toBe(docxMime);
  expect(result.size).toBe(4);
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/evaluation/projects/p/report-archives/a/exports/qa-docx-v1?archive_hash=h",
    { method: "GET", cache: "no-store" },
  ]);
});
it("never turns an export error into a downloaded document or retries", async () => {
  mockedFetch.mockResolvedValue(
    new Response(JSON.stringify({ detail: "Archive receipt changed" }), {
      status: 409,
    }),
  );
  await expect(evaluationReportDocx("evaluation/export")).rejects.toThrow(
    "Archive receipt changed",
  );
  expect(mockedFetch).toHaveBeenCalledTimes(1);
});
it("rejects successful HTML/login or unknown renderer responses", async () => {
  for (const headers of [
    { "Content-Type": "text/html", "X-DevPilot-Renderer": "qa-docx-v1" },
    { "Content-Type": docxMime, "X-DevPilot-Renderer": "qa-docx-v2" },
  ]) {
    mockedFetch.mockResolvedValue(new Response("UNTRUSTED", { headers }));
    await expect(evaluationReportDocx("evaluation/export")).rejects.toThrow(
      "Invalid report export",
    );
  }
});
it("bounds export downloads before saving a file", async () => {
  mockedFetch.mockResolvedValue(
    new Response("oversize", {
      headers: {
        "Content-Type": docxMime,
        "X-DevPilot-Renderer": "qa-docx-v1",
        "Content-Length": "524289",
      },
    }),
  );
  await expect(evaluationReportDocx("evaluation/export")).rejects.toThrow(
    "Invalid report export",
  );
});

it("rejects a disguised non-ZIP and cancels a chunked oversized body", async () => {
  const headers = {
    "Content-Type": docxMime,
    "X-DevPilot-Renderer": "qa-docx-v1",
  };
  mockedFetch.mockResolvedValue(new Response("not a ZIP", { headers }));
  await expect(evaluationReportDocx("evaluation/export")).rejects.toThrow(
    "Invalid report export",
  );
  const cancel = rs.fn();
  mockedFetch.mockResolvedValue(
    new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new Uint8Array(524289));
        },
        cancel,
      }),
      { headers },
    ),
  );
  await expect(evaluationReportDocx("evaluation/export")).rejects.toThrow(
    "Invalid report export",
  );
  expect(cancel).toHaveBeenCalledOnce();
});

it("independent Word uses its own pinned renderer and rejects the owner renderer", async () => {
  const route =
    "evaluation/projects/p/independent-report-archives/a/exports/independent-qa-docx-v1?archive_hash=h";
  mockedFetch.mockResolvedValue(
    new Response(new Uint8Array([80, 75, 3, 4]), {
      headers: {
        "Content-Type": docxMime,
        "X-DevPilot-Renderer": "independent-qa-docx-v1",
      },
    }),
  );
  expect((await evaluationIndependentReportDocx(route)).size).toBe(4);
  expect(mockedFetch.mock.calls[0]).toEqual([
    "/backend/api/" + route,
    { method: "GET", cache: "no-store" },
  ]);
  mockedFetch.mockResolvedValue(
    new Response(new Uint8Array([80, 75, 3, 4]), {
      headers: {
        "Content-Type": docxMime,
        "X-DevPilot-Renderer": "qa-docx-v1",
      },
    }),
  );
  await expect(evaluationIndependentReportDocx(route)).rejects.toThrow(
    "Invalid report export",
  );
  expect(mockedFetch).toHaveBeenCalledTimes(2);
});
it.each(["html", "oversize", "signature", "stream-error", "http-error"])(
  "independent Word fails closed without retry: %s",
  async (kind) => {
    const headers = {
      "Content-Type": docxMime,
      "X-DevPilot-Renderer": "independent-qa-docx-v1",
    };
    let response: Response;
    if (kind === "http-error") response = new Response("{}", { status: 503 });
    else if (kind === "html")
      response = new Response("<html>Login</html>", {
        headers: { ...headers, "Content-Type": "text/html" },
      });
    else if (kind === "oversize")
      response = new Response(new Uint8Array(524289), { headers });
    else if (kind === "stream-error")
      response = new Response(
        new ReadableStream({
          pull(controller) {
            controller.error(new Error("stream interrupted"));
          },
        }),
        { headers },
      );
    else response = new Response(new Uint8Array([1, 2, 3, 4]), { headers });
    mockedFetch.mockResolvedValue(response);
    await expect(
      evaluationIndependentReportDocx("independent/export"),
    ).rejects.toThrow();
    expect(mockedFetch).toHaveBeenCalledTimes(1);
  },
);
