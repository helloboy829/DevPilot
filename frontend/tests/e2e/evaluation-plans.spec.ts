import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const request = {
  id: "r1",
  project_id: "p1",
  component_id: "c1",
  version_label: "Synthetic request v1",
  scope: "request_definition_only",
  protected_hash: "a".repeat(64),
  request_template: {
    schema: "request-template.v1",
    method: "POST",
    origin: "https://example.test:443",
    headers: [],
    fingerprint: "b".repeat(64),
  },
  created_by: "fixture",
  created_at: "2026-11-08T00:00:00Z",
};
const data = {
  id: "d1",
  project_id: "p1",
  name: "Synthetic frozen QA",
  purpose: "baseline",
  revision: 2,
  status: "frozen",
  sample_count: 3,
  content_hash: "c".repeat(64),
  source: {
    label: "Fixture",
    reference: "fixture:qa",
    authorization_basis: "owned synthetic",
    attested: true,
  },
};
function plan(body: Record<string, unknown>) {
  const settings = { ...body };
  delete settings.confirmed;
  return {
    id: "plan1",
    project_id: "p1",
    component_id: "c1",
    request_version_id: "r1",
    dataset_id: "d1",
    version_label: settings.version_label,
    scope: "frozen_definition_only",
    definition_hash: "d".repeat(64),
    definition: {
      ...settings,
      schema: "qa-json-plan.v1",
      scope: "frozen_definition_only",
      project_id: "p1",
      component_id: "c1",
      request_template_fingerprint: "b".repeat(64),
      dataset_purpose: "baseline",
      sample_order: "sample_id_ascending_cycle.v1",
      evaluation_policy: "human_review_required.v1",
      preflight: {
        sample_count: 3,
        request_count: (settings.limits as { request_count: number })
          .request_count,
        total_body_bytes: 120,
      },
    },
    created_by: "fixture",
    created_at: "2026-11-08T00:00:00Z",
  };
}
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
    route.fulfill({
      json: {
        datasets: route.request().url().includes("/p1/")
          ? [
              data,
              {
                ...data,
                id: "draft",
                name: "Synthetic draft",
                status: "draft",
              },
            ]
          : [],
      },
    }),
  );
  await page.route("**/api/evaluation/projects/*/components", (route) =>
    route.fulfill({
      json: {
        components: route.request().url().includes("/p1/")
          ? [
              {
                id: "c1",
                project_id: "p1",
                name_at_link: "Synthetic LLM",
                kind: "llm",
              },
              {
                id: "c2",
                project_id: "p1",
                name_at_link: "Other LLM",
                kind: "llm",
              },
            ]
          : [],
      },
    }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/components/*/request-versions",
    (route) =>
      route.fulfill({
        json: {
          request_versions: route.request().url().includes("/c1/")
            ? [request]
            : [],
        },
      }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/components/*/plans",
    (route) => route.fulfill({ json: { plans: [] } }),
  );
  await page.goto("/workspace/datasets");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p1");
  const panel = page.getByRole("region", {
    name: "Frozen QA plans",
    exact: true,
  });
  await panel
    .getByRole("button", { name: "Load / refresh plan sources", exact: true })
    .click();
  await panel
    .getByRole("combobox", { name: "Plan component", exact: true })
    .selectOption("c1");
  await expect(
    panel.getByRole("combobox", { name: "Request version", exact: true }),
  ).toBeEnabled();
  return panel;
}
async function fill(page: Page) {
  const panel = await setup(page);
  await panel
    .getByRole("combobox", { name: "Request version", exact: true })
    .selectOption("r1");
  await panel
    .getByRole("combobox", { name: "QA dataset version", exact: true })
    .selectOption("d1");
  await panel
    .getByLabel("Plan version label", { exact: true })
    .fill("Synthetic plan v1");
  await panel.getByLabel("Input JSON pointer", { exact: true }).fill("/q");
  await panel.getByLabel("Output JSON pointer", { exact: true }).fill("/a");
  return panel;
}
const consent = /I confirm freezing this definition only/;
test("freeze a complete QA plan without target calls, gold reads or browser persistence", async ({
  page,
}) => {
  const forbidden: string[] = [];
  page.on("request", (r) => {
    if (/\/(references|open|execute|debug\/send)(?:$|\?)/.test(r.url()))
      forbidden.push(r.url());
  });
  const panel = await fill(page);
  let writes = 0;
  await page.route(
    "**/api/evaluation/projects/p1/components/c1/plans",
    async (route) => {
      writes++;
      const body = route.request().postDataJSON();
      expect(body).toEqual({
        version_label: "Synthetic plan v1",
        request_version_id: "r1",
        request_protected_hash: "a".repeat(64),
        dataset_id: "d1",
        dataset_revision: 2,
        dataset_hash: "c".repeat(64),
        binding: {
          schema: "qa-json-binding.v1",
          input_pointer: "/q",
          output_pointer: "/a",
        },
        response_mode: "json_text",
        limits: {
          mode: "effectiveness",
          concurrency: 1,
          request_count: 3,
          timeout_ms: 30000,
          wall_time_ms: 300000,
          max_total_body_bytes: 1048576,
        },
        confirmed: true,
      });
      await route.fulfill({ json: plan(body) });
    },
  );
  const freeze = panel.getByRole("button", {
    name: "Freeze plan definition",
    exact: true,
  });
  await expect(freeze).toBeDisabled();
  await expect(
    panel
      .getByLabel("QA dataset version")
      .getByRole("option", { name: /Synthetic draft/ }),
  ).toHaveCount(0);
  await panel.getByRole("checkbox", { name: consent }).check();
  await freeze.click();
  await expect(panel.getByRole("status")).toContainText(
    "not execution approval",
  );
  await expect(
    panel.getByText("Synthetic plan v1", { exact: true }),
  ).toBeVisible();
  await panel.getByText("Inspect frozen settings", { exact: true }).click();
  await expect(
    panel.getByText("human_review_required.v1", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("checkbox", { name: consent }),
  ).not.toBeChecked();
  expect(writes).toBe(1);
  expect(forbidden).toEqual([]);
  const storage = await page.evaluate(() =>
    JSON.stringify({ ...localStorage, ...sessionStorage }),
  );
  expect(storage).not.toMatch(
    /Synthetic plan|request_protected_hash|dataset_revision|input_pointer/,
  );
});
test("parameter edits, refresh, and component switching revoke confirmation", async ({
  page,
}) => {
  const panel = await fill(page);
  await panel.getByRole("checkbox", { name: consent }).check();
  await panel.getByLabel("Concurrency", { exact: true }).fill("2");
  await expect(
    panel.getByRole("checkbox", { name: consent }),
  ).not.toBeChecked();
  await panel.getByRole("checkbox", { name: consent }).check();
  await panel
    .getByRole("button", { name: "Refresh versions and plans", exact: true })
    .click();
  await expect(
    panel.getByRole("checkbox", { name: consent }),
  ).not.toBeChecked();
  await expect(
    panel.getByRole("combobox", { name: "Request version", exact: true }),
  ).toHaveValue("");
  await panel
    .getByRole("combobox", { name: "Plan component", exact: true })
    .selectOption("c2");
  await expect(
    panel
      .getByRole("combobox", { name: "Request version", exact: true })
      .getByRole("option", { name: "Synthetic request v1" }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: "Freeze plan definition", exact: true }),
  ).toBeDisabled();
});
for (const failure of [409, 503, "abort"] as const) {
  test(`unknown or failed write ${failure} requires explicit reload; no automatic retry`, async ({
    page,
  }) => {
    const panel = await fill(page);
    let writes = 0;
    await page.route(
      "**/api/evaluation/projects/p1/components/c1/plans",
      async (route) => {
        if (route.request().method() !== "POST") {
          await route.fulfill({ json: { plans: [] } });
          return;
        }
        writes++;
        if (failure === "abort") await route.abort();
        else
          await route.fulfill({
            status: failure,
            json: { detail: "SYNTHETIC_HIDDEN_ERROR" },
          });
      },
    );
    await panel.getByRole("checkbox", { name: consent }).check();
    await panel
      .getByRole("button", { name: "Freeze plan definition", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText("Refresh and inspect");
    await expect(panel).not.toContainText("SYNTHETIC_HIDDEN_ERROR");
    await expect(
      panel.getByRole("checkbox", { name: consent }),
    ).not.toBeChecked();
    await panel.getByRole("checkbox", { name: consent }).check();
    await expect(
      panel.getByRole("button", {
        name: "Freeze plan definition",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      panel.getByLabel("Plan version label", { exact: true }),
    ).toHaveValue("Synthetic plan v1");
    expect(writes).toBe(1);
    await panel
      .getByRole("button", { name: "Refresh versions and plans", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toHaveCount(0);
    await expect(
      panel.getByRole("combobox", { name: "Request version", exact: true }),
    ).toHaveValue("");
  });
}
test("performance limits are explicit; invalid count blocks freeze and root-string output is opt-in", async ({
  page,
}) => {
  const panel = await fill(page);
  await panel
    .getByRole("combobox", { name: "Evaluation mode", exact: true })
    .selectOption("performance");
  await panel.getByLabel("Request count", { exact: true }).fill("2");
  await panel.getByRole("checkbox", { name: consent }).check();
  await expect(
    panel.getByRole("button", { name: "Freeze plan definition", exact: true }),
  ).toBeDisabled();
  await panel.getByLabel("Request count", { exact: true }).fill("7");
  await panel
    .getByRole("checkbox", {
      name: "Response root is a JSON string",
      exact: true,
    })
    .check();
  await panel.getByRole("checkbox", { name: consent }).check();
  await page.route(
    "**/api/evaluation/projects/p1/components/c1/plans",
    async (route) => {
      const body = route.request().postDataJSON();
      expect(body.binding.output_pointer).toBe("");
      expect(body.limits.request_count).toBe(7);
      expect(body.limits.mode).toBe("performance");
      await route.fulfill({ json: plan(body) });
    },
  );
  await panel
    .getByRole("button", { name: "Freeze plan definition", exact: true })
    .click();
  await expect(panel.getByRole("status")).toBeVisible();
  await expect(panel).toContainText("No TTFT");
});
test("late source response cannot populate another project", async ({
  page,
}) => {
  const panel = await setup(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    "**/api/evaluation/projects/p1/components/c2/request-versions",
    async (route) => {
      await gate;
      await route.fulfill({
        json: {
          request_versions: [
            { ...request, id: "late", version_label: "LATE_SYNTHETIC" },
          ],
        },
      });
    },
  );
  await panel
    .getByRole("combobox", { name: "Plan component", exact: true })
    .selectOption("c2");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p2");
  release();
  await expect(
    page.getByRole("region", { name: "Frozen QA plans", exact: true }),
  ).not.toContainText("LATE_SYNTHETIC");
  await expect(
    page.getByRole("button", {
      name: "Load / refresh plan sources",
      exact: true,
    }),
  ).toBeEnabled();
});
test("Chinese small-screen panel has labelled controls and bounded layout", async ({
  page,
  context,
  baseURL,
}) => {
  await context.addCookies([{ name: "locale", value: "zh-CN", url: baseURL! }]);
  await page.setViewportSize({ width: 390, height: 844 });
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({ json: { projects: [{ id: "p1", name: "合成项目" }] } }),
  );
  await page.route("**/api/evaluation/projects/p1/datasets", (route) =>
    route.fulfill({ json: { datasets: [] } }),
  );
  await page.goto("/workspace/datasets");
  await page
    .getByRole("combobox", { name: "选择项目", exact: true })
    .selectOption("p1");
  const panel = page.getByRole("region", {
    name: "冻结 QA 评测计划",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "加载 / 刷新计划来源", exact: true }),
  ).toBeVisible();
  await expect(panel).toContainText("不启动测试");
  expect(
    await panel.evaluate(
      (element) => element.scrollWidth <= element.clientWidth + 1,
    ),
  ).toBe(true);
});

test("project switching keeps exactly one registry and one plan panel with independent state", async ({
  page,
}) => {
  await setup(page);
  const project = page.getByRole("combobox", {
    name: "Select project",
    exact: true,
  });
  for (const id of ["p2", "p1", "p2", "p1"]) {
    await project.selectOption(id);
    const registry = page.getByRole("region", {
      name: "Project components & submissions",
      exact: true,
    });
    const plans = page.getByRole("region", {
      name: "Frozen QA plans",
      exact: true,
    });
    await expect(registry).toHaveCount(1);
    await expect(plans).toHaveCount(1);
    await expect(
      registry.getByRole("combobox", {
        name: "Registered component",
        exact: true,
      }),
    ).toHaveCount(1);
    await expect(
      plans.getByRole("combobox", { name: "Plan component", exact: true }),
    ).toHaveCount(1);
    await expect(
      plans.getByRole("combobox", { name: "Request version", exact: true }),
    ).toHaveValue("");
  }
});
