import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  fetchReportTemplates,
  generateReportPreview,
} from "@/core/reports/api";
import type { ReportFacts } from "@/core/reports/types";

const mockedFetch = rs.mocked(fetcher);
const template = {
  id: "synthetic-template",
  version: "1.0.0",
  language: "en",
  name: "Synthetic",
  schema_version: "report-facts.v1",
};
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
beforeEach(() => {
  mockedFetch.mockReset();
});

describe("reports API", () => {
  it("uses the authenticated fetcher without storing template responses", async () => {
    mockedFetch.mockResolvedValueOnce(response({ templates: [template] }));
    await expect(fetchReportTemplates()).resolves.toEqual([template]);
    expect(mockedFetch).toHaveBeenCalledWith("/backend/api/reports/templates", {
      cache: "no-store",
    });
  });
  it("pins the exact template version and never supplies a verified source or actor", async () => {
    mockedFetch.mockResolvedValueOnce(response({ status: "DRAFT" }));
    const facts = { title: "Synthetic fixture" } as ReportFacts;
    await generateReportPreview(template, facts);
    const [url, init] = mockedFetch.mock.calls[0]!;
    expect(url).toBe("/backend/api/reports/preview");
    expect(init?.method).toBe("POST");
    expect(init?.cache).toBe("no-store");
    expect(JSON.parse(init?.body as string)).toEqual({
      template_id: template.id,
      template_version: "1.0.0",
      facts,
    });
  });
  it("exposes safe server validation messages", async () => {
    mockedFetch.mockResolvedValueOnce(
      response({ detail: "Invalid outcome counts" }, 422),
    );
    await expect(
      generateReportPreview(template, {} as ReportFacts),
    ).rejects.toThrow("Invalid outcome counts");
  });
});
