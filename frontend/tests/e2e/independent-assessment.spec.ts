import { expect, test, type Page } from "@playwright/test";

import {
  assessment,
  assessmentArchive,
  assessmentId,
  assessmentMetadata,
} from "../fixtures/assessment";

import { mockLangGraphAPI } from "./utils/mock-api";
async function setup(page: Page) {
  mockLangGraphAPI(page, { threads: [] });
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
  await page.route("**/api/evaluation/projects/*/datasets", (route) =>
    route.fulfill({ json: { datasets: [] } }),
  );
  await page.route("**/api/evaluation/projects/*/review-runs", (route) =>
    route.fulfill({
      json: {
        runs: [
          {
            id: "r1",
            component_name: "Synthetic component",
            plan_label: "Frozen plan",
          },
        ],
      },
    }),
  );
}
function panel(page: Page) {
  return page.getByRole("region", {
    name: "Independent all-sample assessments",
    exact: true,
  });
}
async function select(page: Page) {
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p1");
  await panel(page)
    .getByRole("button", {
      name: "Load / refresh assessment runs",
      exact: true,
    })
    .click();
  await panel(page)
    .getByRole("combobox", { name: "Independent assessment run", exact: true })
    .selectOption("r1");
}
async function noOverflow(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual((page.viewportSize()?.width ?? 0) + 1);
}
for (const width of [1440, 390]) {
  test(`independent all-sample assessment archive and pinned history at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 950 });
    await setup(page);
    let previewReads = 0,
      writes = 0,
      archiveReads = 0,
      outbound = 0,
      created = "";
    const literal =
      '<img src="https://invalid.example/pixel"> https://invalid.example';
    page.on("request", (request) => {
      if (
        /invalid\.example|\/api\/(models|component-tests).*\/(run|debug)|\/assistant/.test(
          request.url(),
        )
      )
        outbound++;
    });
    await page.route(
      "**/api/evaluation/projects/p1/review-runs/r1/**",
      async (route) => {
        const request = route.request(),
          path = new URL(request.url()).pathname;
        if (path.endsWith("/independent-assessment")) {
          previewReads++;
          return route.fulfill({
            json: assessment({ component_name: literal }),
          });
        }
        if (path.endsWith("/assessments"))
          return route.fulfill({ json: [assessmentMetadata()] });
        const id = path.split("/").at(-1)!;
        if (request.method() === "POST") {
          writes++;
          created = id;
          expect(request.postDataJSON()).toEqual({
            summary_hash: "b".repeat(64),
            expected_previous_revision: 1,
            confirmed: true,
          });
          return route.fulfill({
            json: assessmentArchive({
              id,
              revision: 2,
              assessment: assessment({ component_name: literal }),
            }),
          });
        }
        archiveReads++;
        return route.fulfill({ json: assessmentArchive() });
      },
    );
    await page.goto("/workspace/datasets");
    expect(previewReads).toBe(0);
    expect(writes).toBe(0);
    await select(page);
    const region = panel(page);
    await region
      .getByRole("button", {
        name: "Load / refresh independent preview and revisions",
        exact: true,
      })
      .click();
    const current = region.getByRole("region", {
      name: "Current independent assessment preview",
      exact: true,
    });
    await expect(current.getByText("1 / 2 · 50.00%")).toBeVisible();
    await expect(current.getByText(/<img src=/)).toBeVisible();
    await expect(current.locator("img,a")).toHaveCount(0);
    await noOverflow(page);
    const archive = region.getByRole("button", {
      name: "Archive independent assessment revision",
      exact: true,
    });
    await expect(archive).toBeDisabled();
    const consent = region.getByRole("checkbox", {
      name: /I viewed the independent/,
    });
    await consent.focus();
    await page.keyboard.press("Space");
    await archive.focus();
    await page.keyboard.press("Enter");
    await expect(region.getByRole("status")).toContainText("not approval");
    expect(writes).toBe(1);
    expect(created).toMatch(/^[0-9a-f]{32}$/);
    await region
      .getByRole("button", { name: "Open assessment revision 1", exact: true })
      .click();
    await expect(
      region.getByRole("region", {
        name: "Opened immutable assessment revision",
        exact: true,
      }),
    ).toContainText("Archived revision #1");
    expect(previewReads).toBe(1);
    expect(archiveReads).toBe(1);
    expect(outbound).toBe(0);
    const storage = await page.evaluate(() =>
      JSON.stringify({
        local: { ...localStorage },
        session: { ...sessionStorage },
      }),
    );
    expect(storage).not.toContain("invalid.example");
    expect(storage).not.toContain(created);
    await noOverflow(page);
  });
}
test("unknown archive is retained across project switches and uses same-ID GET only after 404", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 950 });
  await setup(page);
  let created = "",
    writes = 0,
    reads = 0;
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/r1/**",
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/independent-assessment"))
        return route.fulfill({ json: assessment() });
      if (path.endsWith("/assessments")) return route.fulfill({ json: [] });
      if (route.request().method() === "POST") {
        writes++;
        created = path.split("/").at(-1)!;
        return route.abort("failed");
      }
      reads++;
      expect(path.endsWith(created)).toBe(true);
      if (reads === 1)
        return route.fulfill({
          status: 404,
          json: { detail: "SECRET_RAW_ERROR" },
        });
      return route.fulfill({ json: assessmentArchive({ id: created }) });
    },
  );
  await page.goto("/workspace/datasets");
  await select(page);
  let region = panel(page);
  await region
    .getByRole("button", {
      name: "Load / refresh independent preview and revisions",
      exact: true,
    })
    .click();
  await region
    .getByRole("checkbox", { name: /I viewed the independent/ })
    .check();
  await region
    .getByRole("button", {
      name: "Archive independent assessment revision",
      exact: true,
    })
    .click();
  await expect(region.getByRole("alert")).toBeVisible();
  expect(writes).toBe(1);
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p2");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p1");
  region = panel(page);
  await region
    .getByRole("combobox", { name: "Independent assessment run", exact: true })
    .selectOption("r1");
  await expect(region.getByText("Assessment ID: " + created)).toBeVisible();
  await region
    .getByRole("button", {
      name: "Reconcile same assessment ID (GET)",
      exact: true,
    })
    .click();
  await expect(region.getByRole("alert")).not.toContainText("SECRET_RAW_ERROR");
  await expect(
    region.getByRole("button", {
      name: "Load / refresh independent preview and revisions",
      exact: true,
    }),
  ).toBeDisabled();
  await region
    .getByRole("button", {
      name: "Reconcile same assessment ID (GET)",
      exact: true,
    })
    .click();
  await expect(region.getByRole("status")).toBeVisible();
  expect(writes).toBe(1);
  expect(reads).toBe(2);
  await noOverflow(page);
});
test("owner summary cannot masquerade as independent assessment and historical lookup does not need a preview", async ({
  page,
}) => {
  await setup(page);
  let previewReads = 0;
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/r1/**",
    (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/independent-assessment")) {
        previewReads++;
        return route.fulfill({
          json: { schema: "qa-human-summary.v1", acceptance: "approved" },
        });
      }
      if (path.endsWith("/assessments")) return route.fulfill({ json: [] });
      return route.fulfill({ json: assessmentArchive() });
    },
  );
  await page.goto("/workspace/datasets");
  await select(page);
  const region = panel(page);
  await region
    .getByLabel("Assessment revision ID", { exact: true })
    .fill(assessmentId);
  await region
    .getByRole("button", { name: "Open assessment by ID (GET)", exact: true })
    .click();
  await expect(
    region.getByRole("region", {
      name: "Opened immutable assessment revision",
      exact: true,
    }),
  ).toBeVisible();
  expect(previewReads).toBe(0);
  await region
    .getByRole("button", {
      name: "Load / refresh independent preview and revisions",
      exact: true,
    })
    .click();
  await expect(region.getByRole("alert")).toBeVisible();
  await expect(
    region.getByRole("button", {
      name: "Archive independent assessment revision",
      exact: true,
    }),
  ).toBeDisabled();
});
