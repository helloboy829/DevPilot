import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const width of [1440, 390]) {
  test(`verified human summary retains its denominator and invalidates on scope changes (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    mockLangGraphAPI(page, { threads: [] });
    let reads = 0;
    let sends = 0;
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
              plan_label: "Plan v1",
              status: "recording_finished",
              request_count: 2,
            },
          ],
        },
      }),
    );
    await page.route(
      "**/api/evaluation/projects/p1/review-runs/r1/summary",
      async (route) => {
        reads++;
        await route.fulfill({
          json: {
            schema: "qa-human-summary.v1",
            scope: "verified_human_summary_preview",
            run_id: "r1",
            run_status: "recording_finished",
            project_id: "p1",
            component_id: "c1",
            component_name: "Synthetic component",
            plan_id: "plan1",
            plan_label: "Plan v1",
            plan_hash: "a".repeat(64),
            summary_hash: "b".repeat(64),
            counts: { pass: 1, fail: 0, uncertain: 0, unreviewed: 1 },
            technical_counts: { collected: 2, other: 0 },
            human_pass_rate: { numerator: 1, denominator: 2, value: 0.5 },
            readiness: "provisional",
            blockers: ["unreviewed"],
            acceptance: "not_approved",
          },
        });
      },
    );
    await page.route("**/api/request-debugger/send", async (route) => {
      sends++;
      await route.abort();
    });
    await page.goto("/workspace/datasets");
    const project = page.getByRole("combobox", {
      name: "Select project",
      exact: true,
    });
    await project.selectOption("p1");
    const review = page.getByRole("region", {
      name: "Human result review",
      exact: true,
    });
    await review
      .getByRole("button", { name: "Load / refresh review runs", exact: true })
      .click();
    await review
      .getByRole("combobox", { name: "Review run", exact: true })
      .selectOption("r1");
    const summary = review.getByRole("region", {
      name: "Fixed-denominator review summary",
      exact: true,
    });
    await expect(summary).toBeVisible();
    expect(reads).toBe(0);
    await summary
      .getByRole("button", {
        name: "Load / refresh verified summary",
        exact: true,
      })
      .click();
    await expect(summary.getByText("50.00%", { exact: true })).toBeVisible();
    await expect(summary.getByText("1 / 2", { exact: true })).toBeVisible();
    await expect(
      summary.getByText("Unreviewed: 1", { exact: true }),
    ).toBeVisible();
    await expect(
      summary.getByText(/not an approved report or acceptance verdict/),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await review
      .getByRole("button", { name: "Load / refresh review runs", exact: true })
      .click();
    await expect(review.getByText("50.00%", { exact: true })).toHaveCount(0);
    await project.selectOption("p2");
    await expect(page.getByText("50.00%", { exact: true })).toHaveCount(0);
    expect(reads).toBe(1);
    expect(sends).toBe(0);
    const storage = await page.evaluate(() =>
      JSON.stringify({
        local: { ...localStorage },
        session: { ...sessionStorage },
      }),
    );
    expect(storage).not.toContain("summary_hash");
    expect(storage).not.toContain("Synthetic component");
  });
}
