import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const spec = {
  version: "request.v1",
  method: "POST",
  url: "https://example.test/imported",
  headers: [["Authorization", "Bearer SYNTHETIC_ORIGINAL"]],
  body: '{"q":"synthetic"}',
};
const metadata = {
  id: "v1",
  project_id: "p1",
  component_id: "c1",
  version_label: "reviewed-v1",
  scope: "request_definition_only",
  protected_hash: "a".repeat(64),
  created_by: "fixture",
  created_at: "2026-11-08T00:00:00Z",
  request_template: {
    schema: "request-template.v1",
    method: "POST",
    origin: "https://example.test:443",
    headers: [["Authorization", "DEVPILOT_REQUEST_HEADER_1"]],
    fingerprint: "b".repeat(64),
  },
};
async function setup(page: Page) {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/component-tests/components*", (route) =>
    route.fulfill({ json: { components: [] } }),
  );
  await page.route("**/api/component-tests/debug/parse", (route) =>
    route.fulfill({ json: { spec } }),
  );
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({
      json: { projects: [{ id: "p1", name: "Synthetic project" }] },
    }),
  );
  await page.route("**/api/evaluation/projects/p1/components", (route) =>
    route.fulfill({
      json: {
        components: [
          { id: "c1", name_at_link: "Synthetic component", kind: "llm" },
        ],
      },
    }),
  );
  await page.goto("/workspace/component-tests");
}
async function chooseScope(page: Page) {
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Load / refresh projects", exact: true })
    .click();
  await dialog
    .getByRole("combobox", { name: "Project", exact: true })
    .selectOption("p1");
  await dialog
    .getByRole("combobox", { name: "Project component", exact: true })
    .selectOption("c1");
  return dialog;
}
async function importRequest(page: Page) {
  await page
    .getByLabel("cURL", { exact: true })
    .fill("curl https://example.test/imported");
  await page.getByRole("button", { name: "Import cURL", exact: true }).click();
  await expect(page.getByLabel("Request URL", { exact: true })).toBeVisible();
}

test("save the edited request snapshot under a project component without sending or browser persistence", async ({
  page,
}) => {
  let sends = 0;
  let writes = 0;
  await page.route("**/api/component-tests/debug/send", (route) => {
    sends++;
    return route.fulfill({ status: 500 });
  });
  await page.route(
    "**/api/evaluation/projects/p1/components/c1/request-versions",
    async (route) => {
      if (route.request().method() === "POST") {
        writes++;
        expect(route.request().postDataJSON()).toEqual({
          version_label: "reviewed-v1",
          confirmed: true,
          request: {
            method: "POST",
            url: "https://example.test/edited?key=SYNTHETIC_QUERY",
            headers: [["Authorization", "Bearer SYNTHETIC_EDITED"]],
            body: '{"q":"SYNTHETIC_EDITED_BODY"}',
          },
        });
        await route.fulfill({ json: metadata });
      } else await route.fulfill({ json: { request_versions: [metadata] } });
    },
  );
  await setup(page);
  await importRequest(page);
  await page
    .getByLabel("Request URL", { exact: true })
    .fill("https://example.test/edited?key=SYNTHETIC_QUERY");
  await page.getByText("Reveal / edit headers", { exact: true }).click();
  await page
    .getByLabel("Request headers", { exact: true })
    .fill(JSON.stringify([["Authorization", "Bearer SYNTHETIC_EDITED"]]));
  await page
    .getByLabel("Request body", { exact: true })
    .fill('{"q":"SYNTHETIC_EDITED_BODY"}');
  await page
    .getByRole("button", { name: "Save request version", exact: true })
    .click();
  const dialog = await chooseScope(page);
  await dialog
    .getByLabel("Request version label", { exact: true })
    .fill("reviewed-v1");
  const save = dialog.getByRole("button", {
    name: "Save encrypted version",
    exact: true,
  });
  await expect(save).toBeDisabled();
  await dialog
    .getByRole("checkbox", { name: /I confirm encrypted storage/ })
    .check();
  await save.click();
  await expect(dialog.getByRole("status")).toContainText("definition only");
  await expect(dialog.getByText("reviewed-v1", { exact: true })).toBeVisible();
  await expect(dialog).not.toContainText("SYNTHETIC_EDITED");
  await expect(
    dialog.getByRole("checkbox", { name: /I confirm encrypted storage/ }),
  ).not.toBeChecked();
  const stored = await page.evaluate(() =>
    JSON.stringify({
      local: { ...localStorage },
      session: { ...sessionStorage },
    }),
  );
  expect(stored).not.toMatch(/SYNTHETIC_EDITED|SYNTHETIC_QUERY/);
  expect(writes).toBe(1);
  expect(sends).toBe(0);
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await page
    .getByRole("button", { name: "Clear request and credentials", exact: true })
    .click();
  await expect(page.getByLabel("Request URL", { exact: true })).toHaveCount(0);
});

test("saved metadata remains readable without importing a request or a configured encryption key", async ({
  page,
}) => {
  let writes = 0;
  await page.route(
    "**/api/evaluation/projects/p1/components/c1/request-versions",
    (route) => {
      if (route.request().method() !== "GET") writes++;
      return route.fulfill({ json: { request_versions: [metadata] } });
    },
  );
  await setup(page);
  await page
    .getByRole("button", { name: "View request versions", exact: true })
    .click();
  const dialog = await chooseScope(page);
  await dialog
    .getByRole("button", { name: "Load saved versions", exact: true })
    .click();
  await expect(dialog.getByText("reviewed-v1", { exact: true })).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Save encrypted version", exact: true }),
  ).toHaveCount(0);
  await expect(dialog).toContainText("https://example.test:443");
  expect(writes).toBe(0);
});

test("invalid headers cannot open save; failed writes preserve edits and require fresh confirmation", async ({
  page,
}) => {
  let writes = 0;
  await page.route(
    "**/api/evaluation/projects/p1/components/c1/request-versions",
    (route) => {
      if (route.request().method() === "POST") writes++;
      return route.fulfill({
        status: 503,
        json: { detail: "SYNTHETIC_INTERNAL_ERROR" },
      });
    },
  );
  await setup(page);
  await importRequest(page);
  await page.getByText("Reveal / edit headers", { exact: true }).click();
  await page
    .getByLabel("Request headers", { exact: true })
    .fill('{"Authorization":"SYNTHETIC_VALUE"}');
  await page
    .getByRole("button", { name: "Save request version", exact: true })
    .click();
  await expect(
    page
      .getByRole("region", { name: "Request debugger", exact: true })
      .getByRole("alert"),
  ).toContainText("array of string name/value pairs");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByLabel("Request headers", { exact: true }).fill("[]");
  await page
    .getByRole("button", { name: "Save request version", exact: true })
    .click();
  const dialog = await chooseScope(page);
  await dialog
    .getByLabel("Request version label", { exact: true })
    .fill("retry-v1");
  await dialog
    .getByRole("checkbox", { name: /I confirm encrypted storage/ })
    .check();
  await dialog
    .getByRole("button", { name: "Save encrypted version", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    "request-encryption key",
  );
  await expect(dialog).not.toContainText("SYNTHETIC_INTERNAL_ERROR");
  await expect(
    dialog.getByLabel("Request version label", { exact: true }),
  ).toHaveValue("retry-v1");
  await expect(
    dialog.getByRole("button", { name: "Save encrypted version", exact: true }),
  ).toBeDisabled();
  expect(writes).toBe(1);
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.getByLabel("Request URL", { exact: true })).toHaveValue(
    spec.url,
  );
});

test("Chinese mobile metadata dialog stays accessible and within the viewport", async ({
  page,
  context,
  baseURL,
}) => {
  if (!baseURL) throw new Error("Missing baseURL");
  await context.addCookies([{ name: "locale", value: "zh-CN", url: baseURL }]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route(
    "**/api/evaluation/projects/p1/components/c1/request-versions",
    (route) => route.fulfill({ json: { request_versions: [metadata] } }),
  );
  await setup(page);
  await page.getByRole("button", { name: "查看请求版本", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "加载 / 刷新项目", exact: true })
    .click();
  await dialog
    .getByRole("combobox", { name: "项目", exact: true })
    .selectOption("p1");
  await dialog
    .getByRole("combobox", { name: "项目组件", exact: true })
    .selectOption("c1");
  await dialog
    .getByRole("button", { name: "加载已保存版本", exact: true })
    .click();
  await expect(dialog.getByText("reviewed-v1", { exact: true })).toBeVisible();
  await expect(dialog).toContainText("列表只返回元数据");
  const dimensions = await dialog.evaluate((node) => ({
    width: node.getBoundingClientRect().width,
    scroll: node.scrollWidth,
    client: node.clientWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(390);
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client + 1);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});
