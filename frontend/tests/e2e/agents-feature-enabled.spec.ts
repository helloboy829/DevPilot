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

test("a member configures an evaluation assistant without a model and retries a conflict", async ({
  page,
}) => {
  mockLangGraphAPI(page, { agents: [] });
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "synthetic-member",
        email: "member@example.test",
        system_role: "member",
        needs_setup: false,
      },
    }),
  );
  const saved: Record<string, unknown>[] = [];
  let attempts = 0;
  let releaseConflict: () => void = () => {
    throw new Error("Request not started");
  };
  const conflictReady = new Promise<void>((resolve) => {
    releaseConflict = resolve;
  });
  let modelCalls = 0;
  await page.route("**/api/langgraph/**/stream", (route) => {
    modelCalls++;
    return route.abort();
  });
  await page.route("**/api/agents", async (route) => {
    if (route.request().method() === "GET")
      return route.fulfill({ json: { agents: saved } });
    const payload = route.request().postDataJSON();
    expect(payload.model).toBeNull();
    expect(payload.tool_groups).toEqual([]);
    expect(payload.skills).toEqual([]);
    expect(payload.soul).toContain("human");
    if (++attempts === 1) {
      await conflictReady;
      return route.fulfill({
        status: 409,
        json: { detail: "Synthetic conflict" },
      });
    }
    saved.push(payload);
    return route.fulfill({ json: payload });
  });
  await page.goto("/workspace/agents");
  await page
    .getByRole("button", { name: "Configure manually", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Role preset").selectOption("result-review");
  await dialog.getByLabel("Assistant name").fill("My-Reviewer");
  await dialog
    .getByRole("button", { name: "Save assistant", exact: true })
    .click();
  await expect(dialog.getByLabel("Assistant name")).toBeDisabled();
  await expect(
    dialog.getByRole("button", { name: "Saving…", exact: true }),
  ).toBeDisabled();
  await expect.poll(() => attempts).toBe(1);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(dialog).toBeVisible();
  await dialog
    .locator("form")
    .evaluate((form) =>
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      ),
    );
  expect(attempts).toBe(1);
  releaseConflict();
  await expect(dialog.getByRole("alert")).toContainText("Could not save");
  await expect(dialog.getByLabel("Assistant name")).toHaveValue("My-Reviewer");
  await dialog
    .getByRole("button", { name: "Save assistant", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("my-reviewer", { exact: true })).toBeVisible();
  expect(modelCalls).toBe(0);
});
