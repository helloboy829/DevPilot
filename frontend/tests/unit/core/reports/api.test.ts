import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  fetchReportTemplates,
  fetchReportAssistantStatus,
  requestReportAdvice,
  generateReportPreview,
} from "@/core/reports/api";
import type { ReportFacts, ReportAdvisory } from "@/core/reports/types";

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

it("assistant status does not trigger a run and requests are explicit about consent", async () => {
  mockedFetch.mockResolvedValueOnce(
    response({ available: false, reason: "disabled" }),
  );
  await expect(fetchReportAssistantStatus()).resolves.toEqual({
    available: false,
    reason: "disabled",
  });
  expect(mockedFetch.mock.calls[0]![1]?.method).toBeUndefined();
  mockedFetch.mockResolvedValueOnce(response({ advice: {} }));
  await requestReportAdvice(template, {} as ReportFacts);
  expect(JSON.parse(mockedFetch.mock.calls[1]![1]!.body as string)).toEqual({
    template_id: template.id,
    template_version: template.version,
    facts: {},
    consent: true,
  });
});

it("only explicit caller-supplied attachments are sent to the preview", async () => {
  mockedFetch.mockResolvedValueOnce(response({ status: "DRAFT" }));
  const advisory = {
    summary: "Synthetic",
    human_confirmed: true,
  } as ReportAdvisory;
  await generateReportPreview(template, {} as ReportFacts, advisory);
  expect(
    JSON.parse(mockedFetch.mock.calls[0]![1]!.body as string).advisory,
  ).toEqual(advisory);
});
