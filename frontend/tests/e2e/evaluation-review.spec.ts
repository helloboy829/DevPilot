import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("explicit human review keeps Q/A/reference together, preserves revisions and clears scope", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  const run = {
    id: "run1",
    component_name: "Synthetic component",
    plan_label: "QA v1",
    status: "recording_finished",
    request_count: 1,
  };
  const reviews: {
    revision: number;
    decision: string;
    note: string;
    reviewer_id: string;
    created_at_ms: number;
  }[] = [];
  let openCount = 0;
  let writes = 0;
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
    route.fulfill({ json: { runs: [run] } }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/run1/**",
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/reviews")) {
        const body = route.request().postDataJSON();
        expect(body.expected_revision).toBe(reviews.length);
        expect(body.case_hash).toBe("b".repeat(64));
        expect(body.confirmed).toBe(true);
        writes++;
        reviews.push({
          revision: reviews.length + 1,
          decision: body.decision,
          note: body.note,
          reviewer_id: "synthetic-reviewer",
          created_at_ms: 1800000000000,
        });
        await route.fulfill({
          json: {
            revision: reviews.length,
            decision: body.decision,
            case_hash: body.case_hash,
          },
        });
      } else if (path.endsWith("/cases/1")) {
        openCount++;
        await route.fulfill({
          json: {
            scope: "human_review_only",
            run_id: run.id,
            ordinal: 1,
            sample_id: "q1",
            component_name: run.component_name,
            plan_label: run.plan_label,
            state: "observed",
            input: "SYNTHETIC_INPUT",
            expected: "SYNTHETIC_GOLD",
            output: "<img src=x onerror=alert(1)> SYNTHETIC_OUTPUT",
            source_ref: "synthetic://local",
            slice_tag: "default",
            evidence_hash: "a".repeat(64),
            case_hash: "b".repeat(64),
            technical: {
              kind: "output_collected",
              http_status: 200,
              body_bytes: 35,
              elapsed_ms: 10,
            },
            review_revision: reviews.length,
            reviews,
          },
        });
      } else
        await route.fulfill({
          json: {
            scope: "human_review_only",
            run,
            cases: [
              {
                ordinal: 1,
                sample_id: "q1",
                state: "observed",
                kind: "output_collected",
                has_output_evidence: true,
                review_revision: reviews.length,
                review_decision: reviews.at(-1)?.decision ?? null,
              },
            ],
            counts: {
              pass: reviews.at(-1)?.decision === "pass" ? 1 : 0,
              fail: 0,
              uncertain: reviews.at(-1)?.decision === "uncertain" ? 1 : 0,
              unreviewed: reviews.length ? 0 : 1,
            },
            offset: 0,
            limit: 100,
          },
        });
    },
  );
  await page.route("**/api/request-debugger/send", async (route) => {
    sends++;
    await route.abort();
  });
  await page.goto("/workspace/datasets");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p1");
  const panel = page.getByRole("region", {
    name: "Human result review",
    exact: true,
  });
  await expect(panel).toBeVisible();
  expect(openCount).toBe(0);
  await panel
    .getByRole("button", { name: "Load / refresh review runs", exact: true })
    .click();
  await panel
    .getByRole("combobox", { name: "Review run", exact: true })
    .selectOption("run1");
  await panel.getByRole("button", { name: "Load cases", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: /Open case 1/ }),
  ).toBeVisible();
  expect(openCount).toBe(0);
  await panel.getByRole("button", { name: /Open case 1/ }).click();
  await expect(
    panel.getByText("SYNTHETIC_INPUT", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText("SYNTHETIC_GOLD", { exact: true }),
  ).toBeVisible();
  await expect(panel.getByText(/<img src=x onerror=alert/)).toBeVisible();
  await expect(panel.locator('img[src="x"]')).toHaveCount(0);
  await panel
    .getByLabel("Review note", { exact: true })
    .fill("Synthetic first review");
  await panel.getByRole("radio", { name: "Pass", exact: true }).check();
  await panel
    .getByRole("checkbox", { name: /I confirm this human decision/ })
    .check();
  await panel
    .getByRole("button", { name: "Save review revision", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("appended");
  await panel.getByRole("button", { name: "Load cases", exact: true }).click();
  await panel.getByRole("button", { name: /Open case 1/ }).click();
  await expect(
    panel.getByText("Synthetic first review", { exact: true }),
  ).toBeVisible();
  await panel
    .getByLabel("Review note", { exact: true })
    .fill("Synthetic revised review");
  await panel.getByRole("radio", { name: "Uncertain", exact: true }).check();
  await panel
    .getByRole("checkbox", { name: /I confirm this human decision/ })
    .check();
  await panel
    .getByRole("button", { name: "Save review revision", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("appended");
  expect(writes).toBe(2);
  expect(reviews.map((row) => row.decision)).toEqual(["pass", "uncertain"]);
  expect(sends).toBe(0);
  const storage = await page.evaluate(() =>
    JSON.stringify({
      local: { ...localStorage },
      session: { ...sessionStorage },
    }),
  );
  expect(storage).not.toContain("SYNTHETIC_");
  expect(storage).not.toContain("Synthetic first review");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p2");
  await expect(page.getByText("SYNTHETIC_GOLD", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("combobox", { name: "Review run", exact: true }),
  ).toHaveValue("");
});
