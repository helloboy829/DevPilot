import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../fixtures/synthetic-independent-qa-docx-v1.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as {
  document: {
    id: string;
    archive_hash: string;
    revision: number;
    markdown: string;
    template: unknown;
  };
  docx_base64: string;
};
async function openArchive(page: Page) {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/assistant", (route) =>
    route.fulfill({ json: { available: false } }),
  );
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({
      json: {
        projects: [
          { id: "p1", name: "Synthetic project" },
          { id: "p2", name: "Other project" },
        ],
      },
    }),
  );
  const forbidden: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      request.method() !== "GET" ||
      /\/gold|\/cases|\/execute|\/debug|\/review-tasks|\/assessments|invalid\.example/.test(
        request.url(),
      )
    )
      forbidden.push(path);
  });
  await page.route("**/api/evaluation/projects/p1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/review-runs"))
      return route.fulfill({ json: { runs: [] } });
    if (path.endsWith("/independent-report-templates"))
      return route.fulfill({
        json: { templates: [fixture.document.template] },
      });
    if (path.endsWith("/independent-report-archives"))
      return route.fulfill({ json: [] });
    if (path.endsWith("/" + fixture.document.id))
      return route.fulfill({ json: fixture.document });
    return route.fulfill({ status: 404, json: { detail: "Unexpected route" } });
  });
  await page.goto("/workspace/reports");
  const region = page.getByRole("region", {
    name: "Independent historical report archives",
    exact: true,
  });
  await region
    .getByRole("button", {
      name: "Load independent archive projects",
      exact: true,
    })
    .click();
  await region
    .getByLabel("Independent archive project", { exact: true })
    .selectOption("p1");
  await region
    .getByRole("button", {
      name: "Load independent runs, templates and archives",
      exact: true,
    })
    .click();
  await region
    .getByLabel("Known independent archive ID", { exact: true })
    .fill(fixture.document.id);
  await region
    .getByRole("button", {
      name: "Open pinned independent archive",
      exact: true,
    })
    .click();
  const opened = region.getByRole("region", {
    name: "Opened independent historical archive",
    exact: true,
  });
  await expect(opened).toBeVisible();
  return { region, opened, forbidden };
}
for (const width of [1440, 390])
  test(`independent frozen Word download at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 });
    const { opened, forbidden } = await openArchive(page);
    let exports = 0;
    await page.route(
      "**/independent-report-archives/*/exports/independent-qa-docx-v1?*",
      (route) => {
        exports++;
        const url = new URL(route.request().url());
        expect(url.pathname).toBe(
          `/api/evaluation/projects/p1/independent-report-archives/${fixture.document.id}/exports/independent-qa-docx-v1`,
        );
        expect(url.searchParams.get("archive_hash")).toBe(
          fixture.document.archive_hash,
        );
        expect(route.request().method()).toBe("GET");
        return route.fulfill({
          contentType:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          headers: {
            "x-devpilot-renderer": "independent-qa-docx-v1",
            "cache-control": "private, no-store",
          },
          body: Buffer.from(fixture.docx_base64, "base64"),
        });
      },
    );
    expect(exports).toBe(0);
    const button = opened.getByRole("button", {
      name: "Download independent historical Word draft",
      exact: true,
    });
    await button.focus();
    const waiting = page.waitForEvent("download");
    await page.keyboard.press("Enter");
    const download = await waiting;
    expect(download.suggestedFilename()).toBe(
      `independent-qa-report-${fixture.document.id}-r${fixture.document.revision}.docx`,
    );
    const chunks: Buffer[] = [];
    for await (const chunk of await download.createReadStream())
      chunks.push(Buffer.from(chunk));
    expect(Buffer.concat(chunks)).toEqual(
      Buffer.from(fixture.docx_base64, "base64"),
    );
    await expect(opened.locator("pre")).toHaveText(fixture.document.markdown);
    await expect(opened.locator("img,a")).toHaveCount(0);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width + 1);
    expect(exports).toBe(1);
    expect(forbidden).toEqual([]);
  });
test("failed independent Word download never retries or saves an error page", async ({
  page,
}) => {
  const { opened, forbidden } = await openArchive(page);
  let exports = 0;
  const downloads: string[] = [];
  page.on("download", (download) =>
    downloads.push(download.suggestedFilename()),
  );
  await page.route(
    "**/independent-report-archives/*/exports/independent-qa-docx-v1?*",
    (route) => {
      exports++;
      return route.fulfill({
        status: 409,
        json: { detail: "Receipt changed" },
      });
    },
  );
  await opened
    .getByRole("button", {
      name: "Download independent historical Word draft",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Operation unconfirmed" }),
  ).toBeVisible();
  expect(exports).toBe(1);
  expect(downloads).toEqual([]);
  expect(forbidden).toEqual([]);
});
