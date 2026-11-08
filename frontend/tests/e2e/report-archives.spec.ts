import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import type {
  ArchiveRequest,
  ReportArchive,
} from "../../src/core/evaluation/report-archive-types";
import type { ReviewSummary } from "../../src/core/evaluation/review-types";

import { mockLangGraphAPI } from "./utils/mock-api";

const wordFixture = JSON.parse(
  readFileSync(
    new URL("../fixtures/synthetic-qa-docx-v1.json", import.meta.url),
    "utf8",
  ),
) as { document: ReportArchive; docx_base64: string };

function summary(index: number): ReviewSummary {
  return {
    schema: "qa-human-summary.v1",
    scope: "verified_human_summary_preview",
    project_id: "p1",
    run_id: String(index).repeat(32),
    component_id: "c" + index,
    component_name: "Synthetic component " + index,
    plan_id: "plan" + index,
    plan_label: "QA " + index,
    plan_hash: "c".repeat(64),
    summary_hash: String(index).repeat(64),
    run_status: "recording_finished",
    counts: { pass: index, fail: 2 - index, uncertain: 0, unreviewed: 0 },
    technical_counts: { collected: 2, other: 0 },
    human_pass_rate: { numerator: index, denominator: 2, value: index / 2 },
    readiness: "review_complete",
    blockers: [],
    acceptance: "not_approved",
  };
}
async function setup(page: Page, uncertain = false, initial?: ReportArchive) {
  mockLangGraphAPI(page, { threads: [] });
  const summaries = [summary(1), summary(2)];
  const archives = new Map<string, ReportArchive>();
  if (initial) archives.set(initial.id, initial);
  const writes: { id: string; body: ArchiveRequest }[] = [];
  const checks: string[] = [];
  let outbound = 0;
  const template = {
    id: "verified-qa-project-en",
    version: "1.0.0",
    language: "en" as const,
    layout: { heading: "Synthetic DRAFT" },
  };
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({ json: { templates: [] } }),
  );
  await page.route("**/api/reports/project/templates", (route) =>
    route.fulfill({ json: { templates: [] } }),
  );
  await page.route("**/api/reports/assistant", (route) =>
    route.fulfill({ json: { available: false, reason: "disabled" } }),
  );
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({
      json: { projects: [{ id: "p1", name: "Synthetic project" }] },
    }),
  );
  await page.route("**/api/evaluation/projects/p1/review-runs", (route) =>
    route.fulfill({
      json: {
        runs: summaries.map((s) => ({
          id: s.run_id,
          component_name: s.component_name,
          plan_label: s.plan_label,
          request_count: 2,
          status: s.run_status,
        })),
      },
    }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/summary",
    (route) =>
      route.fulfill({
        json: summaries.find((s) => route.request().url().includes(s.run_id)),
      }),
  );
  await page.route("**/api/evaluation/projects/p1/report-templates", (route) =>
    route.fulfill({ json: { templates: [template] } }),
  );
  await page.route("**/api/evaluation/projects/p1/report-archives", (route) =>
    route.fulfill({
      json: {
        archives: [...archives.values()].map(
          ({ components: _c, markdown: _m, ...a }) => a,
        ),
      },
    }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/report-archives/*",
    async (route) => {
      const id = route.request().url().split("/").at(-1)!;
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as ArchiveRequest;
        writes.push({ id, body });
        expect(Object.keys(body).sort()).toEqual([
          "confirmed",
          "sources",
          "supersedes_id",
          "template_id",
          "template_version",
          "title",
        ]);
        expect(body.confirmed).toBe(true);
        const parent = body.supersedes_id
          ? archives.get(body.supersedes_id)
          : undefined;
        const components = body.sources.map(
          (r) =>
            summaries.find(
              (s) => s.run_id === r.run_id && s.summary_hash === r.summary_hash,
            )!,
        );
        const result: ReportArchive = {
          schema: "qa-project-report-archive.v1",
          scope: "immutable_qa_report_draft",
          id,
          project_id: "p1",
          project_name: "Synthetic project",
          root_id: parent?.root_id ?? id,
          revision: (parent?.revision ?? 0) + 1,
          supersedes_id: body.supersedes_id,
          title: body.title,
          template,
          template_hash: "a".repeat(64),
          components,
          acceptance: "not_approved",
          archive_hash: "f".repeat(64),
          created_at_ms: 1800000000000,
          markdown:
            "# Synthetic archived DRAFT\n" +
            components
              .map(
                (s) =>
                  s.component_name +
                  " " +
                  (s.human_pass_rate.value * 100).toFixed(2) +
                  "%",
              )
              .join("\n") +
            "\n<img src=x onerror=alert(1)>",
        };
        archives.set(id, result);
        if (uncertain) await route.abort("failed");
        else await route.fulfill({ json: result });
      } else {
        checks.push(id);
        const result = archives.get(id);
        await route.fulfill({
          status: result ? 200 : 404,
          json: result ?? { detail: "Not found" },
        });
      }
    },
  );
  await page.route("**/api/request-debugger/send", async (route) => {
    outbound++;
    await route.abort();
  });
  await page.goto("/workspace/reports");
  await expect(page.getByTestId("report-notice")).toContainText(
    "separate archive workflow",
  );
  const panel = page.getByRole("region", {
    name: "Verified platform report archive",
    exact: true,
  });
  expect(writes).toHaveLength(0);
  expect(checks).toHaveLength(0);
  await panel
    .getByRole("button", { name: "Load projects", exact: true })
    .click();
  await panel.getByLabel("Report project", { exact: true }).selectOption("p1");
  await panel
    .getByRole("button", {
      name: "Load runs, templates and archives",
      exact: true,
    })
    .click();
  async function add(index: number) {
    await panel
      .getByLabel("Evidence run", { exact: true })
      .selectOption(String(index).repeat(32));
    await panel
      .getByRole("button", { name: "Verify selected summary", exact: true })
      .click();
    await panel
      .getByRole("button", { name: "Add verified component", exact: true })
      .click();
  }
  return { panel, add, writes, checks, archives, outbound: () => outbound };
}
for (const width of [1280, 390]) {
  test(`multi-component frozen archive and revision at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const { panel, add, writes, archives, outbound } = await setup(page);
    await add(1);
    await add(2);
    await panel
      .getByLabel("Archive title", { exact: true })
      .fill("Synthetic report");
    await panel
      .getByLabel("Confirm immutable draft storage", { exact: true })
      .check();
    await panel
      .getByRole("button", { name: "Archive verified draft", exact: true })
      .click();
    const detail = panel.getByTestId("archive-document");
    await expect(
      detail.getByText(/Historical draft.*Revision 1/),
    ).toBeVisible();
    await expect(detail.locator("pre")).toContainText("50.00%");
    await expect(detail.locator("pre")).toContainText("100.00%");
    await expect(detail.locator('img[src="x"]')).toHaveCount(0);
    const frozen = archives.get(writes[0]!.id)!;
    const original = JSON.stringify(frozen);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      detail
        .getByRole("button", {
          name: "Download archived Markdown",
          exact: true,
        })
        .click(),
    ]);
    expect(download.suggestedFilename()).toBe(`qa-report-${frozen.id}-r1.md`);
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(Buffer.from(chunk));
    expect(Buffer.concat(chunks).toString("utf8")).toBe(frozen.markdown);
    await add(1);
    await add(2);
    await detail
      .getByRole("button", { name: "Use as revision parent", exact: true })
      .click();
    await panel
      .getByLabel("Confirm immutable draft storage", { exact: true })
      .check();
    await panel
      .getByRole("button", { name: "Archive verified draft", exact: true })
      .click();
    await expect(
      detail.getByText(/Historical draft.*Revision 2/),
    ).toBeVisible();
    expect(writes).toHaveLength(2);
    expect(writes[1]!.id).not.toBe(writes[0]!.id);
    expect(writes[1]!.body.supersedes_id).toBe(writes[0]!.id);
    expect(JSON.stringify(archives.get(writes[0]!.id))).toBe(original);
    expect(outbound()).toBe(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
test("unknown write is reconciled by same-ID GET without a second PUT", async ({
  page,
}) => {
  const { panel, add, writes, checks } = await setup(page, true);
  await add(1);
  await panel
    .getByLabel("Archive title", { exact: true })
    .fill("Synthetic report");
  await panel
    .getByLabel("Confirm immutable draft storage", { exact: true })
    .check();
  await panel
    .getByRole("button", { name: "Archive verified draft", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(
    panel.getByLabel("Archive title", { exact: true }),
  ).toBeDisabled();
  await panel
    .getByRole("button", { name: "Check pending archive receipt", exact: true })
    .click();
  await expect(panel.getByTestId("archive-document")).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(checks).toEqual([writes[0]!.id]);
});

for (const width of [1280, 390]) {
  test(`Word draft downloads real frozen DOCX at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const frozen = wordFixture.document;
    const { panel, writes, outbound } = await setup(page, false, frozen);
    let exports = 0;
    await page.route(
      "**/report-archives/*/exports/qa-docx-v1?*",
      async (route) => {
        exports++;
        const url = new URL(route.request().url());
        expect(url.pathname).toContain(
          `/report-archives/${frozen.id}/exports/qa-docx-v1`,
        );
        expect(url.searchParams.get("archive_hash")).toBe(frozen.archive_hash);
        expect(route.request().method()).toBe("GET");
        await route.fulfill({
          contentType:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          headers: {
            "x-devpilot-renderer": "qa-docx-v1",
            "cache-control": "private, no-store",
          },
          body: Buffer.from(wordFixture.docx_base64, "base64"),
        });
      },
    );
    await panel.getByRole("button", { name: /Open Synthetic draft/ }).click();
    const detail = panel.getByTestId("archive-document");
    expect(exports).toBe(0);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      detail
        .getByRole("button", { name: "Download Word draft", exact: true })
        .click(),
    ]);
    expect(download.suggestedFilename()).toBe(
      `qa-report-${frozen.id}-r${frozen.revision}.docx`,
    );
    const chunks: Buffer[] = [];
    for await (const chunk of await download.createReadStream())
      chunks.push(Buffer.from(chunk));
    expect(Buffer.concat(chunks)).toEqual(
      Buffer.from(wordFixture.docx_base64, "base64"),
    );
    expect(exports).toBe(1);
    expect(writes).toHaveLength(0);
    expect(outbound()).toBe(0);
    await expect(detail.locator("pre")).toHaveText(frozen.markdown);
  });
}

test("failed Word export preserves frozen draft without downloading an error page", async ({
  page,
}) => {
  const frozen = wordFixture.document;
  const { panel, writes } = await setup(page, false, frozen);
  let exports = 0;
  const downloads: string[] = [];
  page.on("download", (file) => downloads.push(file.suggestedFilename()));
  await page.route(
    "**/report-archives/*/exports/qa-docx-v1?*",
    async (route) => {
      exports++;
      await route.fulfill({ status: 409, json: { detail: "Receipt changed" } });
    },
  );
  await panel.getByRole("button", { name: /Open Synthetic draft/ }).click();
  const detail = panel.getByTestId("archive-document");
  await detail
    .getByRole("button", { name: "Download Word draft", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(
    detail.getByRole("button", { name: "Download Word draft", exact: true }),
  ).toBeEnabled();
  await expect(detail.locator("pre")).toHaveText(frozen.markdown);
  expect(exports).toBe(1);
  expect(downloads).toEqual([]);
  expect(writes).toHaveLength(0);
});
