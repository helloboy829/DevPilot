import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("QA execution is separately authorized, receipted and cancelled without debugger sends", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  let writes = 0;
  let cancels = 0;
  let sends = 0;
  let key = "";
  const plan = {
    id: "plan1",
    version_label: "Synthetic plan",
    definition_hash: "b".repeat(64),
    definition: {
      limits: {
        mode: "effectiveness",
        request_count: 2,
        concurrency: 2,
        timeout_ms: 1000,
        wall_time_ms: 10000,
      },
    },
  };
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({
      json: { projects: [{ id: "p1", name: "Synthetic project" }] },
    }),
  );
  await page.route("**/api/evaluation/projects/p1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/datasets"))
      return route.fulfill({ json: { datasets: [] } });
    if (path.endsWith("/components"))
      return route.fulfill({
        json: {
          components: [{ id: "c1", name_at_link: "Synthetic component" }],
        },
      });
    if (path.endsWith("/plans"))
      return route.fulfill({ json: { plans: [plan] } });
    if (path.endsWith("/execution-policy"))
      return route.fulfill({
        json: {
          enabled: true,
          max_active_runs: 2,
          max_reserved_concurrency: 8,
        },
      });
    if (path.endsWith("/execution-runs"))
      return route.fulfill({ json: { executions: [] } });
    if (path.endsWith("/cancel")) {
      cancels++;
      return route.fulfill({
        json: {
          id: key,
          run_id: "run1",
          state: "interrupted",
          reservation_held: false,
        },
      });
    }
    if (route.request().method() === "PUT") {
      expect(route.request().postDataJSON()).toEqual({
        plan_id: "plan1",
        plan_hash: plan.definition_hash,
        confirmed: true,
        target_authorized: true,
      });
      expect(path).toMatch(/execution-runs\/[0-9a-f]{32}$/);
      key = path.split("/").at(-1)!;
      writes++;
      return route.fulfill({
        json: {
          id: key,
          run_id: "run1",
          state: "queued",
          reservation_held: true,
        },
      });
    }
    return route.fulfill({ json: {} });
  });
  await page.route("**/api/request-debugger/send", async (route) => {
    sends++;
    await route.abort();
  });
  await page.goto("/workspace/datasets");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p1");
  const panel = page.getByRole("region", {
    name: "Authorized evaluation execution",
    exact: true,
  });
  await expect(panel).toBeVisible();
  expect(writes).toBe(0);
  await panel
    .getByRole("button", { name: "Load execution workspace", exact: true })
    .click();
  await panel
    .getByRole("combobox", { name: "Execution component", exact: true })
    .selectOption("c1");
  await panel
    .getByRole("button", { name: "Load executable plans", exact: true })
    .click();
  await panel
    .getByRole("combobox", { name: "Execution plan", exact: true })
    .selectOption("plan1");
  const start = panel.getByRole("button", {
    name: "Authorize and queue execution",
    exact: true,
  });
  await expect(start).toBeDisabled();
  await panel
    .getByRole("checkbox", { name: /I am authorized to call/ })
    .check();
  await expect(start).toBeDisabled();
  await panel
    .getByRole("checkbox", { name: /I confirm the frozen plan/ })
    .check();
  await start.click();
  await expect(panel.getByText(/Execution receipt:/)).toContainText("queued");
  await expect(start).toBeDisabled();
  expect(writes).toBe(1);
  await panel
    .getByRole("button", { name: "Cancel this execution", exact: true })
    .click();
  await expect(panel.getByText(/Execution receipt:/)).toContainText(
    "interrupted",
  );
  expect(cancels).toBe(1);
  expect(sends).toBe(0);
  expect(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    ),
  ).not.toContain("plan1");
});
