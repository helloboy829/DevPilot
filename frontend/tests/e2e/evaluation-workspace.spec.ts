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

test("evaluation home is the default workspace and shows real inventory, not invented scores", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/component-tests/components*", (route) =>
    route.fulfill({
      json: {
        components: [
          {
            id: "synthetic",
            name: "Synthetic target",
            enabled: true,
            transport: "http_post",
            response_mode: "blocking",
          },
        ],
      },
    }),
  );
  await page.goto("/workspace");
  await expect(page).toHaveURL(/\/workspace\/evaluations$/);
  await expect(
    page.getByRole("heading", { name: "Evaluation workbench", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Synthetic target/ }),
  ).toBeVisible();
  await expect(
    page.getByText("Not yet implemented", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Start with cURL", exact: true }),
  ).toBeVisible();
});

test("report requirements retain earlier turns and reset without changing entered metrics", async ({
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
  let turn = 0;
  await page.route("**/api/reports/project/intake", async (route) => {
    const body = route.request().postDataJSON();
    expect(body.history).toHaveLength(turn);
    expect(body.consent).toBe(true);
    if (turn === 1) {
      expect(body.history[0].message).toBe("Prepare Synthetic A");
      expect(body.message).toBe("Add Synthetic B too");
    }
    turn++;
    await route.fulfill({
      json: {
        proposal: {
          title: "Synthetic draft",
          project_name: "Synthetic project",
          components: [
            { name: "Synthetic A", version: "v1" },
            ...(turn === 2 ? [{ name: "Synthetic B", version: "v2" }] : []),
          ],
          questions: ["Confirm scope"],
        },
        round: turn,
        conversation_persisted: false,
      },
    });
  });
  await page.goto("/workspace/reports");
  await page.getByTestId("report-total").fill("7");
  const input = page.getByLabel("Describe report requirements", {
    exact: true,
  });
  await input.fill("Prepare Synthetic A");
  await page
    .getByRole("checkbox", { name: /Authorize sending only the requirements/ })
    .check();
  await page
    .getByRole("button", {
      name: "Extract fields / ask missing details",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("log", { name: "Requirements conversation" }),
  ).toContainText("Prepare Synthetic A");
  await input.fill("Add Synthetic B too");
  await expect(
    page.getByRole("button", { name: "Continue conversation", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: /Authorize sending only the requirements/ })
    .check();
  await page
    .getByRole("button", { name: "Continue conversation", exact: true })
    .click();
  await expect(
    page.getByRole("log", { name: "Requirements conversation" }),
  ).toContainText("Synthetic B");
  await page
    .getByRole("button", {
      name: "Confirm project fields (leave metrics unchanged)",
      exact: true,
    })
    .click();
  await expect(page.getByTestId("report-project_name")).toHaveValue(
    "Synthetic project",
  );
  await expect(page.getByTestId("report-total")).toHaveValue("7");
  await page
    .getByRole("button", { name: "Start new conversation", exact: true })
    .click();
  await expect(
    page.getByRole("log", { name: "Requirements conversation" }),
  ).not.toContainText("Prepare Synthetic A");
  await expect(page.getByTestId("report-total")).toHaveValue("7");
});

test("connection presets offer four wire protocols and duplication never reuses a credential", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  const model = {
    name: "synthetic",
    display_name: "Synthetic connection",
    provider_name: "Synthetic gateway",
    provider: "openai_responses",
    model: "synthetic-model",
    base_url: "https://example.test/v1",
    enabled: true,
    has_credential: true,
    parameters: {
      temperature: null,
      top_p: null,
      max_tokens: 100,
      timeout_seconds: 30,
      max_retries: 0,
    },
  };
  await page.route("**/api/model-management", (route) =>
    route.fulfill({ json: { revision: 1, models: [model], roles: {} } }),
  );
  await page.route("**/api/model-management/models", async (route) => {
    const body = route.request().postDataJSON();
    expect(body.model.name).toBe("synthetic-copy");
    expect(body.model.provider).toBe("gemini");
    expect(body.model.api_key).toBeUndefined();
    expect(body.model.parameters.max_tokens).toBe(100);
    await route.fulfill({
      json: {
        revision: 2,
        models: [model, { ...body.model, has_credential: false }],
        roles: {},
      },
    });
  });
  await page.goto("/workspace/models");
  await expect(
    page
      .getByRole("combobox", { name: "Provider adapter", exact: true })
      .locator("option"),
  ).toHaveCount(4);
  await page
    .getByRole("button", { name: "Duplicate profile", exact: true })
    .click();
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
  await expect(
    page.getByLabel("Configuration ID", { exact: true }),
  ).toHaveValue("");
  await page
    .getByLabel("Configuration ID", { exact: true })
    .fill("synthetic-copy");
  await page
    .getByRole("combobox", { name: "Provider adapter", exact: true })
    .selectOption("gemini");
  await page.getByRole("button", { name: "Save model", exact: true }).click();
  await expect(
    page.getByText("Model profile saved", { exact: true }),
  ).toBeVisible();
});
