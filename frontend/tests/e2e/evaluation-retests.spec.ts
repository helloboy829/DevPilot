import { expect, test } from "@playwright/test";

import { baseline, retest, runs, archive } from "../fixtures/qa-retest";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const width of [1440, 390]) {
  test(`same-benchmark retest archive and paired evidence (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    mockLangGraphAPI(page, { threads: [] });
    let writes = 0,
      summaryReads = 0,
      evidenceReads = 0;
    let id = "e".repeat(32);
    await page.route("**/api/evaluation/projects", (route) =>
      route.fulfill({
        json: { projects: [{ id: "p1", name: "Synthetic project" }] },
      }),
    );
    await page.route("**/api/evaluation/projects/p1/review-runs", (route) =>
      route.fulfill({ json: { runs } }),
    );
    await page.route(
      "**/api/evaluation/projects/p1/review-runs/*/summary",
      (route) => {
        summaryReads++;
        return route.fulfill({
          json: route.request().url().includes(baseline.run_id)
            ? baseline
            : retest,
        });
      },
    );
    await page.route(
      "**/api/evaluation/projects/p1/retest-archives/*",
      (route) => {
        id = route.request().url().split("/").at(-1)!;
        if (route.request().method() === "PUT") {
          writes++;
          expect(route.request().postDataJSON()).toEqual({
            baseline: {
              run_id: baseline.run_id,
              summary_hash: baseline.summary_hash,
            },
            retest: {
              run_id: retest.run_id,
              summary_hash: retest.summary_hash,
            },
            confirmed: true,
          });
        }
        return route.fulfill({ json: archive(id) });
      },
    );
    await page.route(
      "**/api/evaluation/projects/p1/review-runs/*/cases/2",
      (route) => {
        evidenceReads++;
        const before = route.request().url().includes(baseline.run_id);
        return route.fulfill({
          json: {
            scope: "human_review_only",
            run_id: before ? baseline.run_id : retest.run_id,
            ordinal: 2,
            sample_id: "z",
            case_hash: (before ? "1" : "2").repeat(64),
            input: "SYNTHETIC_INPUT",
            expected: "SYNTHETIC_GOLD",
            output: before ? "SYNTHETIC_BEFORE" : "SYNTHETIC_AFTER",
            review_revision: 2,
          },
        });
      },
    );
    await page.goto("/workspace/retests");
    expect(summaryReads).toBe(0);
    expect(writes).toBe(0);
    await page
      .getByRole("button", { name: "Load projects", exact: true })
      .click();
    await page
      .getByRole("combobox", { name: "Retest project", exact: true })
      .selectOption("p1");
    await page.getByRole("button", { name: "Load runs", exact: true }).click();
    await page
      .getByRole("combobox", { name: "Baseline run", exact: true })
      .selectOption(baseline.run_id);
    await page
      .getByRole("combobox", { name: "Retest run", exact: true })
      .selectOption(retest.run_id);
    expect(summaryReads).toBe(0);
    await page
      .getByRole("button", { name: "Verify selected summaries", exact: true })
      .click();
    await expect(
      page.getByText("1 / 2 → 2 / 2", { exact: true }),
    ).toBeVisible();
    const save = page.getByRole("button", {
      name: "Verify & archive comparison",
      exact: true,
    });
    await expect(save).toBeDisabled();
    await page.getByRole("checkbox", { name: /I confirm/ }).check();
    await save.click();
    await expect(page.getByText("+50.00 pp", { exact: true })).toBeVisible();
    await expect(page.getByText("Not approved", { exact: true })).toBeVisible();
    expect(writes).toBe(1);
    expect(summaryReads).toBe(2);
    expect(evidenceReads).toBe(0);
    await page
      .getByRole("combobox", { name: "Case filter", exact: true })
      .selectOption("fail_to_pass");
    const table = page.getByRole("table", {
      name: "Frozen sample changes",
      exact: true,
    });
    await expect(table.getByRole("row")).toHaveCount(2);
    await table
      .getByRole("button", { name: "Open evidence z", exact: true })
      .click();
    const evidence = page.getByRole("region", {
      name: "Paired evidence",
      exact: true,
    });
    await expect(
      evidence.getByText("SYNTHETIC_GOLD", { exact: true }),
    ).toBeVisible();
    await expect(
      evidence.getByText("SYNTHETIC_BEFORE", { exact: true }),
    ).toBeVisible();
    await expect(
      evidence.getByText("SYNTHETIC_AFTER", { exact: true }),
    ).toBeVisible();
    expect(evidenceReads).toBe(2);
    await evidence
      .getByRole("button", { name: "Hide evidence", exact: true })
      .click();
    await expect(evidence).toHaveCount(0);
    await expect(page.locator("body")).not.toHaveText(/SYNTHETIC_GOLD/);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await expect(
      page.getByRole("textbox", { name: "Comparison ID", exact: true }),
    ).toHaveValue(id);
  });
}
