import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("signed-in users can open assistants after an operator enables them", async ({
  page,
}) => {
  mockLangGraphAPI(page, { agents: [] });
  await page.addInitScript(() => {
    localStorage.setItem("deerflow.features.agents_api", "false");
  });
  await page.route("**/api/features", (route) =>
    route.fulfill({ json: { agents_api: { enabled: true } } }),
  );
  await page.goto("/workspace/agents");
  await expect(
    page.getByRole("heading", { name: "Custom assistants", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/Every signed-in user can create private assistants/),
  ).toBeVisible();
  const create = page
    .getByRole("button", {
      name: /New Agent|Create Agent|Create Assistant|New assistant/i,
    })
    .first();
  await expect(create).toBeEnabled();
  await create.click();
  await expect(page).toHaveURL(/\/workspace\/agents\/new/);
});
