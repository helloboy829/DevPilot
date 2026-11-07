import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("navigation never inserts new-chat above the product menu", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.goto("/workspace/evaluations");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  const dashboard = sidebar.getByRole("link", {
    name: "Evaluation workbench",
    exact: true,
  });
  const initial = await dashboard.boundingBox();
  expect(initial).not.toBeNull();
  for (const path of ["chats", "agents", "reports"]) {
    await sidebar.locator(`a[href='/workspace/${path}']`).click();
    await expect(page).toHaveURL(new RegExp(`/workspace/${path}`));
    await expect(sidebar.locator("a[href='/workspace/chats/new']")).toHaveCount(
      0,
    );
    expect((await dashboard.boundingBox())!.y).toBeCloseTo(initial!.y, 0);
  }
  await sidebar.locator("a[href='/workspace/chats']").click();
  await page.getByRole("link", { name: "New chat", exact: true }).click();
  await expect(page).toHaveURL(/\/workspace\/chats\/new/);
});

test("five workspace styles persist independently of dark mode", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page);
  await page.goto("/workspace/evaluations?settings=appearance");
  await page.getByRole("button", { name: /^Light\b/ }).click();
  for (const [id, name, light, dark] of [
    ["forest", "Forest lab", "#17634c", "#8cd2b4"],
    ["paper", "Paper studio", "#8b4f23", "#e3b580"],
    ["violet", "Violet atelier", "#7040bf", "#c5a2f3"],
    ["graphite", "Graphite minimal", "#303036", "#c4c4d0"],
    ["console", "Precision console", "#2358c9", "#8eb4ff"],
  ]) {
    const card = page.getByRole("radio", { name, exact: true });
    await card.click();
    await expect(card).toHaveAttribute("aria-checked", "true");
    await expect(page.locator("html")).toHaveAttribute(
      "data-workspace-style",
      id!,
    );
    const primary = () =>
      page.evaluate(() =>
        getComputedStyle(document.documentElement)
          .getPropertyValue("--primary")
          .trim(),
      );
    await expect.poll(primary).toBe(light);
    await page.getByRole("button", { name: /^Dark\b/ }).click();
    await expect.poll(primary).toBe(dark);
    await page.getByRole("button", { name: /^Light\b/ }).click();
  }
  await page.screenshot({
    path: testInfo.outputPath("styles-gallery-light.png"),
  });
  await page.getByRole("radio", { name: "Forest lab", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("radio", { name: "Paper studio", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Space");
  await expect(page.locator("html")).toHaveAttribute(
    "data-workspace-style",
    "paper",
  );
  await page.getByRole("button", { name: /Dark/ }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("html")).toHaveAttribute(
    "data-workspace-style",
    "paper",
  );
  await page.screenshot({ path: testInfo.outputPath("styles-paper-dark.png") });
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("html")).toHaveAttribute(
    "data-workspace-style",
    "paper",
  );
});

test("style gallery fits a mobile viewport and tolerates unavailable storage", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  mockLangGraphAPI(page);
  await page.addInitScript(() => {
    const original = Object.getOwnPropertyDescriptor(
      Storage.prototype,
      "setItem",
    )!.value as (this: Storage, key: string, value: string) => void;
    Storage.prototype.setItem = function (key, value) {
      if (key === "devpilot-workspace-style")
        throw new DOMException("Blocked", "SecurityError");
      return original.call(this, key, value);
    };
  });
  await page.goto("/workspace/evaluations?settings=appearance");
  await page
    .getByRole("radio", { name: "Violet atelier", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute(
    "data-workspace-style",
    "violet",
  );
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});
