import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/reports/project/templates", (route) =>
    route.fulfill({ json: { templates: [] } }),
  );
});

const catalog = {
  templates: [
    {
      id: "component-evaluation-en",
      version: "1.0.0",
      language: "en",
      name: "Evaluation draft",
      schema_version: "report-facts.v1",
    },
    {
      id: "component-evaluation-en",
      version: "2.0.0",
      language: "en",
      name: "Evaluation draft",
      schema_version: "report-facts.v1",
    },
  ],
};

async function fillFacts(page: Page) {
  for (const field of [
    "title",
    "project_name",
    "component_name",
    "component_version",
    "tester",
    "test_period",
    "environment",
    "scope",
    "methodology",
    "evidence_notes",
    "limitations",
  ]) {
    await page.getByTestId(`report-${field}`).fill("Synthetic fixture");
  }
  for (const [field, value] of Object.entries({
    total: "4",
    passed: "2",
    failed: "1",
    errors: "0",
    pending: "1",
    not_run: "0",
  })) {
    await page.getByTestId(`report-${field}`).fill(value);
  }
}

test("report preview pins template version and invalidates old downloads after edits", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({ json: catalog }),
  );
  await page.route("**/api/reports/preview", async (route) => {
    const body = route.request().postDataJSON();
    expect(body.template_version).toBe("1.0.0");
    expect(body.facts.effect.total).toBe(4);
    expect(body.facts.effect.pending).toBe(1);
    expect(body.facts.source).toBeUndefined();
    await route.fulfill({
      json: {
        status: "DRAFT",
        source: "manual_unverified",
        markdown: "# DRAFT\nManual, unverified input",
        facts: body.facts,
        template: { id: body.template_id, version: body.template_version },
        manifest: { generated_by: "synthetic", generated_at: "synthetic" },
        derived: { case_pass_rate: 0.5 },
      },
    });
  });
  await page.goto("/workspace/chats/new");
  await page.getByRole("link", { name: "Reports", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Report workspace" }),
  ).toBeVisible();
  await expect(page.getByTestId("report-notice")).toContainText("unverified");
  await fillFacts(page);
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.getByTestId("report-preview")).toContainText("DRAFT");
  await page.screenshot({
    path: testInfo.outputPath("report-preview.png"),
    fullPage: true,
  });
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download JSON" }).click();
  expect((await downloadEvent).suggestedFilename()).toBe(
    "evaluation-report-draft.json",
  );
  await page.getByTestId("report-title").fill("Revised synthetic title");
  await expect(page.getByTestId("report-preview")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Download JSON" })).toHaveCount(
    0,
  );
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.getByTestId("report-preview")).toBeVisible();
  await page
    .getByLabel("Template version")
    .selectOption("component-evaluation-en@2.0.0");
  await expect(page.getByTestId("report-preview")).toHaveCount(0);
});

test("report catalog errors and validation failures are visible, never downloadable", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({ json: catalog }),
  );
  await page.route("**/api/reports/preview", (route) =>
    route.fulfill({
      status: 422,
      json: { detail: "Counts must sum to total" },
    }),
  );
  await page.goto("/workspace/reports");
  await fillFacts(page);
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Counts must sum to total" }),
  ).toContainText("Counts must sum to total");
  await expect(page.getByRole("button", { name: "Download JSON" })).toHaveCount(
    0,
  );
});

test("an empty template catalog cannot generate a report", async ({ page }) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({ json: { templates: [] } }),
  );
  await page.goto("/workspace/reports");
  await expect(
    page.getByRole("alert").filter({ hasText: "No published templates" }),
  ).toContainText("No published templates");
  await expect(
    page.getByRole("button", { name: "Generate draft", exact: true }),
  ).toBeDisabled();
});

test("template permission errors can be retried without exposing downloads", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  let allowed = false;
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill(
      allowed
        ? { json: catalog }
        : {
            status: 403,
            json: { detail: "Report templates are not authorized" },
          },
    ),
  );
  await page.goto("/workspace/reports");
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Report templates are not authorized" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Generate draft", exact: true }),
  ).toBeDisabled();
  allowed = true;
  await page.getByRole("button", { name: "Reload templates" }).click();
  await expect(page.getByTestId("report-title")).toBeEnabled();
});

test("report inputs are locked while a draft request is in flight", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({ json: catalog }),
  );
  let release: (() => void) | undefined;
  const ready = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/reports/preview", async (route) => {
    await ready;
    await route.fulfill({
      status: 422,
      json: { detail: "Synthetic validation failure" },
    });
  });
  await page.goto("/workspace/reports");
  await fillFacts(page);
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.getByTestId("report-title")).toBeDisabled();
  await expect(page.getByLabel("Template version")).toBeDisabled();
  release!();
  await expect(page.getByTestId("report-title")).toBeEnabled();
  await expect(
    page.getByRole("alert").filter({ hasText: "Synthetic validation failure" }),
  ).toBeVisible();
});

test("performance entry only enables TTFT for content streaming and keeps missing values null", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({ json: catalog }),
  );
  await page.route("**/api/reports/preview", async (route) => {
    const body = route.request().postDataJSON();
    expect(body.facts.effect).toBeNull();
    expect(body.facts.performance.content_streaming).toBe(true);
    expect(body.facts.performance.ttft_mean_ms).toBe(2);
    expect(body.facts.performance.ttft_sample_count).toBe(6);
    expect(body.facts.performance.latency_mean_ms).toBeNull();
    expect(body.facts.performance.latency_sample_count).toBe(0);
    expect(body.facts.performance.throughput_tokens_per_s).toBeNull();
    await route.fulfill({
      json: {
        status: "DRAFT",
        source: "manual_unverified",
        markdown: "# DRAFT\nSynthetic streaming fixture",
      },
    });
  });
  await page.goto("/workspace/reports");
  await fillFacts(page);
  await page.getByLabel("Include effect results", { exact: true }).uncheck();
  await page.getByLabel("Include performance results", { exact: true }).check();
  for (const [key, value] of Object.entries({
    requests: "9",
    successful_requests: "6",
    concurrency: "2",
  })) {
    await page.getByTestId(`report-${key}`).fill(value);
  }
  await expect(page.getByTestId("report-ttft_mean_ms")).toBeDisabled();
  await page
    .getByLabel("Content streaming was enabled", { exact: true })
    .check();
  await page.getByTestId("report-ttft_mean_ms").fill("2");
  await page.getByTestId("report-ttft_sample_count").fill("6");
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.getByTestId("report-preview")).toContainText(
    "Synthetic streaming fixture",
  );
  await page
    .getByLabel("Content streaming was enabled", { exact: true })
    .uncheck();
  await expect(page.getByTestId("report-ttft_mean_ms")).toHaveValue("");
  await expect(page.getByTestId("report-preview")).toHaveCount(0);
});

test("the report workspace has a Chinese form and manual draft warning", async ({
  page,
}) => {
  await page
    .context()
    .addCookies([
      { name: "locale", value: "zh-CN", url: "http://localhost:3000" },
    ]);
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({
      json: {
        templates: [
          {
            id: "component-evaluation-zh",
            version: "1.0.0",
            language: "zh",
            name: "评测草稿",
            schema_version: "report-facts.v1",
          },
        ],
      },
    }),
  );
  await page.goto("/workspace/reports");
  await expect(
    page.getByRole("heading", { name: "评测报告工作台" }),
  ).toBeVisible();
  await expect(page.getByTestId("report-notice")).toContainText("人工填报");
  await expect(page.getByLabel("模板及版本")).toHaveValue(
    "component-evaluation-zh@1.0.0",
  );
  await expect(
    page.getByRole("button", { name: "生成草稿", exact: true }),
  ).toBeVisible();
});

test("report agent is opt-in and suggestions need human confirmation before inclusion", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({ json: catalog }),
  );
  let calls = 0;
  await page.route("**/api/reports/assistant", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        json: {
          available: true,
          reason: "available",
          model_name: "synthetic-model",
        },
      });
    } else {
      calls++;
      const body = route.request().postDataJSON();
      expect(body.consent).toBe(true);
      await route.fulfill({
        json: {
          source: "ai_unverified_advisory",
          model_name: "synthetic-model",
          facts_sha256: "synthetic-hash",
          template_id: body.template_id,
          template_version: body.template_version,
          advice: {
            summary: "<script>synthetic</script>",
            findings: ["Pending cases"],
            recommendations: ["Human review"],
          },
        },
      });
    }
  });
  const attachments: unknown[] = [];
  await page.route("**/api/reports/preview", async (route) => {
    const body = route.request().postDataJSON();
    attachments.push(body.advisory);
    await route.fulfill({
      json: {
        status: "DRAFT",
        facts: body.facts,
        markdown: body.advisory ? "AI unverified appendix" : "Manual draft",
      },
    });
  });
  await page.goto("/workspace/reports");
  await fillFacts(page);
  expect(calls).toBe(0);
  await expect(
    page.getByRole("button", { name: "Request AI suggestions" }),
  ).toBeDisabled();
  await page.getByTestId("report-agent-consent").check();
  await page.getByRole("button", { name: "Request AI suggestions" }).click();
  await expect(page.getByTestId("report-agent-advice")).toContainText(
    "<script>synthetic</script>",
  );
  await expect(
    page.getByTestId("report-agent-advice").locator("script"),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.getByTestId("report-preview")).toContainText(
    "Manual draft",
  );
  expect(attachments[0]).toBeUndefined();
  await page.getByTestId("report-agent-confirm").check();
  await expect(page.getByTestId("report-preview")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.getByTestId("report-preview")).toContainText(
    "AI unverified appendix",
  );
  expect(attachments[1]).toMatchObject({
    human_confirmed: true,
    facts_sha256: "synthetic-hash",
    model_name: "synthetic-model",
  });
  await page.getByTestId("report-title").fill("Synthetic revision");
  await expect(page.getByTestId("report-agent-advice")).toHaveCount(0);
  await expect(page.getByTestId("report-agent-consent")).not.toBeChecked();
  await expect(page.getByTestId("report-preview")).toHaveCount(0);
});

test("unconfigured report agent does not block manual drafting", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({ json: catalog }),
  );
  await page.route("**/api/reports/assistant", (route) =>
    route.fulfill({
      json: { available: false, reason: "model_not_configured" },
    }),
  );
  await page.goto("/workspace/reports");
  await fillFacts(page);
  await expect(
    page.getByText("Agent unavailable", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Request AI suggestions" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Generate draft", exact: true }),
  ).toBeEnabled();
});

test("report agent failures release inputs and still allow a manual draft", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/reports/templates", (route) =>
    route.fulfill({ json: catalog }),
  );
  let release: (() => void) | undefined;
  const ready = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/reports/assistant", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        json: {
          available: true,
          reason: "available",
          model_name: "synthetic",
        },
      });
    } else {
      await ready;
      await route.fulfill({
        status: 503,
        json: { detail: "Synthetic agent unavailable" },
      });
    }
  });
  await page.route("**/api/reports/preview", (route) =>
    route.fulfill({
      json: {
        status: "DRAFT",
        markdown: "Manual draft after unavailable AI",
      },
    }),
  );
  await page.goto("/workspace/reports");
  await fillFacts(page);
  await page.getByTestId("report-agent-consent").check();
  await page.getByRole("button", { name: "Request AI suggestions" }).click();
  await expect(page.getByTestId("report-title")).toBeDisabled();
  await expect(page.getByLabel("Template version")).toBeDisabled();
  release!();
  await expect(
    page.getByRole("alert").filter({ hasText: "Synthetic agent unavailable" }),
  ).toBeVisible();
  await expect(page.getByTestId("report-title")).toBeEnabled();
  await expect(page.getByTestId("report-agent-consent")).not.toBeChecked();
  await expect(page.getByTestId("report-agent-advice")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.getByTestId("report-preview")).toContainText(
    "Manual draft after unavailable AI",
  );
});
