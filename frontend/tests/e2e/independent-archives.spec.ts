import { expect, test, type Page } from "@playwright/test";

import {
  assessmentArchive,
  assessmentMetadata,
  provisionalAssessment,
} from "../fixtures/assessment";
import {
  independentReport,
  independentRetest,
  independentSource,
  independentTemplate,
} from "../fixtures/independent-archive";

import { mockLangGraphAPI } from "./utils/mock-api";
async function setup(page: Page) {
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
}
const region = (page: Page, kind: "report" | "retest") =>
  page.getByRole("region", {
    name:
      kind === "report"
        ? "Independent historical report archives"
        : "Independent historical retest archives",
    exact: true,
  });
async function select(page: Page, kind: "report" | "retest") {
  const r = region(page, kind);
  await r
    .getByRole("button", {
      name: "Load independent archive projects",
      exact: true,
    })
    .click();
  await r
    .getByRole("combobox", { name: "Independent archive project", exact: true })
    .selectOption("p1");
  await r
    .getByRole("button", {
      name: "Load independent runs, templates and archives",
      exact: true,
    })
    .click();
  return r;
}
async function source(
  page: Page,
  kind: "report" | "retest",
  run = "r1",
  id = "e".repeat(32),
) {
  const r = region(page, kind);
  await r
    .getByRole("combobox", { name: "Historical assessment run", exact: true })
    .selectOption(run);
  await r
    .getByRole("button", {
      name: "Load historical independent assessment revisions",
      exact: true,
    })
    .click();
  await expect(
    r.getByRole("combobox", {
      name: "Explicit historical revision",
      exact: true,
    }),
  ).toHaveValue("");
  await r
    .getByRole("combobox", {
      name: "Explicit historical revision",
      exact: true,
    })
    .selectOption(id);
  await r
    .getByRole("button", {
      name: "Open selected historical assessment",
      exact: true,
    })
    .click();
}
for (const width of [1440, 390])
  for (const kind of ["report", "retest"] as const) {
    test(
      kind + " independent historical pinned archive at " + width + "px",
      async ({ page }) => {
        await page.setViewportSize({ width, height: 950 });
        await setup(page);
        let writes = 0,
          reads = 0;
        const sensitive: string[] = [];
        const literal =
          '<img src="https://invalid.example/pixel"> https://invalid.example';
        page.on("request", (request) => {
          // The existing owner report page reads capability metadata on mount.
          // Only that exact GET is allowed; POST would invoke the advisor.
          if (
            request.method() === "GET" &&
            new URL(request.url()).pathname === "/api/reports/assistant"
          )
            return;
          if (
            /invalid\.example|\/gold|\/cases|independent-assessment$|\/execute|\/debug|\/assistant$/.test(
              request.url(),
            )
          )
            sensitive.push(request.url());
        });
        await page.route("**/api/evaluation/projects/p1/**", async (route) => {
          const path = new URL(route.request().url()).pathname;
          if (path.endsWith("/review-runs"))
            return route.fulfill({
              json: {
                runs: ["r1", "r2"].map((id) => ({
                  id,
                  component_name: literal,
                  plan_label: id + " frozen version",
                })),
              },
            });
          if (path.endsWith("/independent-report-templates"))
            return route.fulfill({
              json: { templates: [independentTemplate] },
            });
          const run = path.includes("/r2/") ? "r2" : "r1",
            s = independentSource(run);
          const a = assessmentArchive({
            id: s.assessment_ref.assessment_id,
            run_id: run,
            assessment: s,
          });
          delete (a.assessment as Partial<typeof s>).assessment_ref;
          if (path.endsWith("/assessments"))
            return route.fulfill({
              json: [
                assessmentMetadata({ ...a, id: "f".repeat(32), revision: 2 }),
                assessmentMetadata(a),
              ],
            });
          if (path.includes("/assessments/")) {
            reads++;
            return route.fulfill({
              json: path.endsWith("f".repeat(32))
                ? {
                    ...a,
                    id: "f".repeat(32),
                    revision: 2,
                    assessment: provisionalAssessment(),
                  }
                : a,
            });
          }
          if (path.endsWith("independent-" + kind + "-archives"))
            return route.fulfill({ json: [] });
          if (path.includes("independent-" + kind + "-archives/")) {
            const id = path.split("/").at(-1)!;
            if (route.request().method() === "PUT") {
              writes++;
              const body = route.request().postDataJSON();
              expect(body.confirmed).toBe(true);
              if (kind === "report") {
                expect(body.sources[0].assessment_revision).toBe(1);
                expect(body.sources[0].assessment_id).toBe("e".repeat(32));
              } else {
                expect(body.baseline.run_id).toBe("r1");
                expect(body.retest.run_id).toBe("r2");
              }
            }
            return route.fulfill({
              json:
                kind === "report"
                  ? { ...independentReport(id), markdown: literal }
                  : independentRetest(id),
            });
          }
          return route.fulfill({ status: 404, json: { detail: "Not found" } });
        });
        await page.goto(
          kind === "report" ? "/workspace/reports" : "/workspace/retests",
        );
        expect(reads).toBe(0);
        expect(writes).toBe(0);
        const r = await select(page, kind);
        // A newer provisional revision never silently replaces the explicitly selected complete revision.
        await source(page, kind, "r1", "f".repeat(32));
        await expect(
          r.getByText(/Provisional assessments are ineligible/),
        ).toBeVisible();
        await r
          .getByRole("combobox", {
            name: "Explicit historical revision",
            exact: true,
          })
          .selectOption("e".repeat(32));
        await r
          .getByRole("button", {
            name: "Open selected historical assessment",
            exact: true,
          })
          .click();
        if (kind === "report") {
          await r
            .getByRole("button", {
              name: "Add independent report component",
              exact: true,
            })
            .click();
          await r
            .getByRole("textbox", {
              name: "Independent report title",
              exact: true,
            })
            .fill("Independent draft");
          await r
            .getByRole("combobox", {
              name: "Independent pinned template",
              exact: true,
            })
            .selectOption(independentTemplate.id);
        } else {
          await r
            .getByRole("button", {
              name: "Use as historical baseline",
              exact: true,
            })
            .click();
          await source(page, kind, "r2", "d".repeat(32));
          await r
            .getByRole("button", {
              name: "Use as historical retest",
              exact: true,
            })
            .click();
        }
        const create = r.getByRole("button", {
          name:
            kind === "report"
              ? "Create independent report draft"
              : "Create independent retest comparison",
          exact: true,
        });
        await expect(create).toBeDisabled();
        const consent = r.getByRole("checkbox");
        await consent.focus();
        await page.keyboard.press("Space");
        await expect(create).toBeEnabled();
        await create.click();
        expect(writes).toBe(1);
        const opened = r.getByRole("region", {
          name: "Opened independent historical archive",
          exact: true,
        });
        await expect(opened).toBeVisible();
        await expect(
          opened
            .getByText("1 / 2 · 50.00% · review_complete · not_approved")
            .first(),
        ).toBeVisible();
        await expect(opened.locator("img,a")).toHaveCount(0);
        if (kind === "report") {
          await expect(
            opened.getByText(literal, { exact: true }),
          ).toBeVisible();
          const download = page.waitForEvent("download");
          await opened
            .getByRole("button", {
              name: "Download historical Markdown",
              exact: true,
            })
            .click();
          expect((await download).suggestedFilename()).toMatch(
            /independent-report-.*\.md$/,
          );
        } else
          await expect(
            opened.getByText("All-sample pass-rate delta: 0 / 2 · 0.00 pp"),
          ).toBeVisible();
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth),
        ).toBeLessThanOrEqual(width + 1);
        expect(sensitive).toEqual([]);
      },
    );
  }
