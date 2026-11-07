import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("bind an existing component to a frozen QA version without creating a run", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  const project = { id: "p1", name: "Synthetic project" };
  const dataset = {
    id: "d1",
    project_id: "p1",
    name: "Synthetic QA",
    purpose: "baseline",
    revision: 3,
    status: "frozen",
    sample_count: 1,
    content_hash: "a".repeat(64),
    source: {
      label: "Fixture",
      reference: "fixture:qa",
      authorization_basis: "Synthetic owned",
      attested: true,
    },
  };
  const candidate = {
    schema: "component-inventory.v1",
    source_component_id: "c1",
    name: "Synthetic component",
    transport: "http_post",
    response_mode: "blocking",
    supports_streaming: false,
    validation_type: "manual_review",
    component_fingerprint: "b".repeat(64),
  };
  const linked = {
    id: "l1",
    project_id: "p1",
    source_component_id: "c1",
    name_at_link: "Synthetic component",
    kind: "llm",
    created_at: "2026-11-07T00:00:00Z",
  };
  let isLinked = false;
  let submission: Record<string, unknown> | null = null;
  let writes = 0;
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({ json: { projects: [project] } }),
  );
  await page.route("**/api/evaluation/projects/p1/datasets", (route) =>
    route.fulfill({ json: { datasets: [dataset] } }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/component-candidates",
    (route) => route.fulfill({ json: { components: [candidate] } }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/components",
    async (route) => {
      if (route.request().method() === "POST") {
        expect(route.request().postDataJSON()).toEqual({
          source_component_id: "c1",
          kind: "llm",
        });
        isLinked = true;
        await route.fulfill({ json: linked });
      } else
        await route.fulfill({ json: { components: isLinked ? [linked] : [] } });
    },
  );
  await page.route(
    "**/api/evaluation/projects/p1/components/l1/submissions",
    async (route) => {
      if (route.request().method() === "POST") {
        const payload = route.request().postDataJSON();
        expect(payload).toEqual({
          version_label: "v1",
          dataset_id: "d1",
          dataset_revision: 3,
          dataset_hash: "a".repeat(64),
          component_fingerprint: "b".repeat(64),
          confirmed: true,
        });
        writes++;
        submission = {
          id: "s1",
          project_id: "p1",
          component_id: "l1",
          version_label: "v1",
          dataset_id: "d1",
          dataset_revision: 3,
          dataset_hash: "a".repeat(64),
          dataset_purpose: "baseline",
          component_snapshot: { ...candidate, kind: "llm" },
          scope: "inventory_only",
          submission_hash: "c".repeat(64),
          created_at: "2026-11-07T00:00:00Z",
          created_by: "fixture",
        };
        await route.fulfill({ json: submission });
      } else
        await route.fulfill({
          json: { submissions: submission ? [submission] : [] },
        });
    },
  );
  await page.goto("/workspace/datasets");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p1");
  const panel = page.getByRole("region", {
    name: "Project components & submissions",
  });
  await panel.getByRole("button", { name: "Load / refresh registry" }).click();
  await panel
    .getByRole("combobox", { name: "Registered component", exact: true })
    .selectOption("c1");
  await panel
    .getByRole("combobox", { name: "Component kind", exact: true })
    .selectOption("llm");
  await panel
    .getByRole("button", { name: "Link to project", exact: true })
    .click();
  await panel
    .getByRole("textbox", { name: "Submission version", exact: true })
    .fill("v1");
  await panel
    .getByRole("combobox", { name: "Frozen dataset", exact: true })
    .selectOption("d1");
  const confirm = panel.getByRole("checkbox");
  await confirm.check();
  await panel
    .getByRole("textbox", { name: "Submission version", exact: true })
    .fill("v1-updated");
  await expect(confirm).not.toBeChecked();
  await panel
    .getByRole("textbox", { name: "Submission version", exact: true })
    .fill("v1");
  await confirm.check();
  await panel
    .getByRole("button", {
      name: "Create immutable inventory version",
      exact: true,
    })
    .click();
  await expect(panel.getByText("v1", { exact: true })).toBeVisible();
  await expect(
    panel.getByText("Inventory only — not an executable plan", { exact: true }),
  ).toBeVisible();
  expect(writes).toBe(1);
  await expect(confirm).not.toBeChecked();
  expect(
    await page.evaluate(() => Object.values(localStorage).join(" ")),
  ).not.toContain("Synthetic component");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("registry load failure is not an empty success", async ({ page }) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({
      json: { projects: [{ id: "p1", name: "Synthetic project" }] },
    }),
  );
  await page.route("**/api/evaluation/projects/p1/datasets", (route) =>
    route.fulfill({ json: { datasets: [] } }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/component-candidates",
    (route) => route.fulfill({ status: 503, json: { detail: "unavailable" } }),
  );
  await page.route("**/api/evaluation/projects/p1/components", (route) =>
    route.fulfill({ json: { components: [] } }),
  );
  await page.goto("/workspace/datasets");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p1");
  const panel = page.getByRole("region", {
    name: "Project components & submissions",
  });
  await panel.getByRole("button", { name: "Load / refresh registry" }).click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Link to project", exact: true }),
  ).toBeDisabled();
});
