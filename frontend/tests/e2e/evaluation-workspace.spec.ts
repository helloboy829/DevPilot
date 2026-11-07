import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const projectTemplate = {
  id: "project-evaluation-en",
  version: "1.0.0",
  language: "en",
  name: "Project draft",
  schema_version: "project-report.v1",
};

test("cURL is imported, edited and sent with explicit consent", async ({
  page,
  context,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.route("**/api/component-tests/components*", (route) =>
    route.fulfill({ json: { components: [] } }),
  );
  await page.route("**/api/component-tests/debug/parse", async (route) => {
    expect(route.request().postDataJSON().command).toContain("curl");
    await route.fulfill({
      json: {
        spec: {
          url: "https://example.test/api",
          method: "POST",
          headers: [["Content-Type", "application/json"]],
          body: '{"q":"synthetic"}',
          version: "request.v1",
        },
      },
    });
  });
  await page.route("**/api/component-tests/debug/send", async (route) => {
    const data = route.request().postDataJSON();
    expect(data.consent).toBe(true);
    expect(data.spec.url).toBe("https://example.test/edited");
    await route.fulfill({
      json: {
        status: 200,
        body: '{"answer":"synthetic"}',
        headers: [],
        elapsed_ms: 12,
        size_bytes: 22,
        truncated: false,
      },
    });
  });
  await page.goto("/workspace/component-tests");
  await page
    .getByLabel("cURL", { exact: true })
    .fill("curl https://example.test/api --json '{}'");
  await page.getByRole("button", { name: "Import cURL", exact: true }).click();
  await page
    .getByLabel("Request URL", { exact: true })
    .fill("https://example.test/edited");
  await expect(
    page.getByRole("button", { name: "Send request", exact: true }),
  ).toBeDisabled();
  await page.getByRole("checkbox", { name: /I authorize one request/ }).check();
  await page.getByRole("button", { name: "Send request", exact: true }).click();
  await expect(page.getByLabel("Response body")).toContainText(
    '"answer":"synthetic"',
  );
  await page
    .getByRole("button", { name: "Copy response", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Copied", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Clear request and credentials", exact: true })
    .click();
  await expect(page.getByLabel("Request URL", { exact: true })).toHaveCount(0);
});

test("administrator adds a model and assigns the report role without key echo", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  let catalog = {
    revision: 0,
    models: [] as Record<string, unknown>[],
    roles: {} as Record<string, string>,
  };
  await page.route("**/api/model-management", (route) =>
    route.fulfill({ json: catalog }),
  );
  await page.route("**/api/model-management/models", async (route) => {
    const { model, revision } = route.request().postDataJSON();
    expect(revision).toBe(0);
    expect(model.api_key).toBe("synthetic-secret");
    const metadata = { ...model };
    delete metadata.api_key;
    catalog = {
      revision: 1,
      models: [{ ...metadata, has_credential: true }],
      roles: {},
    };
    await route.fulfill({ json: catalog });
  });
  await page.route("**/api/model-management/roles", async (route) => {
    const data = route.request().postDataJSON();
    expect(data.revision).toBe(1);
    catalog = { ...catalog, revision: 2, roles: data.roles };
    await route.fulfill({ json: catalog });
  });
  await page.goto("/workspace/models");
  await page.getByLabel("Configuration ID", { exact: true }).fill("synthetic");
  await page
    .getByLabel("Provider model ID", { exact: true })
    .fill("synthetic-model");
  await page
    .getByLabel("API Base URL", { exact: true })
    .fill("https://example.test/v1");
  await page.getByLabel("API Key", { exact: true }).fill("synthetic-secret");
  await page.getByRole("button", { name: "Save model", exact: true }).click();
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
  await page
    .getByLabel("report_advisor", { exact: true })
    .selectOption("synthetic");
  await expect(page.getByLabel("report_advisor", { exact: true })).toHaveValue(
    "synthetic",
  );
});

test("requirements require confirmation, then two components form one project draft", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({
      json: {
        templates: [{ ...projectTemplate, id: "component-evaluation-en" }],
      },
    }),
  );
  await page.route("**/api/reports/assistant", (route) =>
    route.fulfill({ json: { available: false, reason: "disabled" } }),
  );
  await page.route("**/api/reports/project/templates", (route) =>
    route.fulfill({ json: { templates: [projectTemplate] } }),
  );
  await page.route("**/api/reports/project/intake", (route) =>
    route.fulfill({
      json: {
        proposal: {
          title: "Synthetic project draft",
          project_name: "Synthetic project",
          components: [
            { name: "Synthetic A", version: "v1" },
            { name: "Synthetic B", version: "v1" },
          ],
          questions: ["Confirm evidence and counters"],
        },
      },
    }),
  );
  await page.route("**/api/reports/project/preview", async (route) => {
    const data = route.request().postDataJSON();
    expect(data.components).toHaveLength(2);
    expect(data.template_version).toBe("1.0.0");
    await route.fulfill({
      json: {
        markdown: "# Synthetic two-component DRAFT",
        manifest: { template_version: "1.0.0", facts_sha256: "synthetic" },
      },
    });
  });
  await page.goto("/workspace/reports");
  await page
    .getByLabel("Describe report requirements", { exact: true })
    .fill("Synthetic two-component project");
  await page
    .getByRole("checkbox", { name: /Authorize sending only the requirements/ })
    .check();
  await page
    .getByRole("button", {
      name: "Extract fields / ask missing details",
      exact: true,
    })
    .click();
  await expect(page.getByTestId("report-project_name")).toHaveValue("");
  await page
    .getByRole("button", {
      name: "Confirm project fields (leave metrics unchanged)",
      exact: true,
    })
    .click();
  await expect(page.getByTestId("report-component_name")).toHaveValue(
    "Synthetic A",
  );
  for (const field of [
    "tester",
    "test_period",
    "environment",
    "scope",
    "methodology",
    "evidence_notes",
    "limitations",
  ])
    await page.getByTestId(`report-${field}`).fill("Synthetic");
  for (const [field, value] of Object.entries({
    total: "2",
    passed: "1",
    failed: "1",
    errors: "0",
    pending: "0",
    not_run: "0",
  }))
    await page.getByTestId(`report-${field}`).fill(value);
  await page
    .getByRole("button", {
      name: "Stage component results from the form below",
      exact: true,
    })
    .click();
  await page.getByTestId("report-component_name").fill("Synthetic B");
  await page
    .getByRole("button", {
      name: "Stage component results from the form below",
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Generate project draft", exact: true })
    .click();
  await expect(
    page.getByText("# Synthetic two-component DRAFT", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Download project Markdown",
      exact: true,
    }),
  ).toBeVisible();
});

test("off-peak schedule freezes bounded parameters and can pause future runs", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/component-tests/components*", (route) =>
    route.fulfill({
      json: {
        components: [
          { id: "synthetic", name: "Synthetic target", enabled: true },
        ],
      },
    }),
  );
  let tasks: Record<string, unknown>[] = [];
  await page.route("**/api/evaluation-schedules", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      expect(body.params.concurrency_levels).toEqual([1, 5]);
      expect(body.consent).toBe(true);
      tasks = [
        {
          ...body,
          id: "synthetic-task",
          status: "enabled",
          plan: {
            component_id: body.component_id,
            test_type: body.test_type,
            params: body.params,
          },
        },
      ];
      await route.fulfill({ json: tasks[0] });
    } else await route.fulfill({ json: { enabled: true, tasks } });
  });
  await page.route(
    "**/api/scheduled-tasks/synthetic-task/pause",
    async (route) => {
      tasks = tasks.map((t) => ({ ...t, status: "paused" }));
      await route.fulfill({ json: tasks[0] });
    },
  );
  await page.goto("/workspace/evaluation-schedules");
  await page
    .getByLabel("Title", { exact: true })
    .fill("Synthetic off-peak test");
  await page
    .getByLabel("Registered component", { exact: true })
    .selectOption("synthetic");
  await page
    .getByRole("checkbox", { name: /I authorize this test scope/ })
    .check();
  await page
    .getByRole("button", { name: "Confirm and save schedule", exact: true })
    .click();
  await expect(
    page.getByText("Synthetic off-peak test", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Pause future runs", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Resume", exact: true }),
  ).toBeVisible();
});
