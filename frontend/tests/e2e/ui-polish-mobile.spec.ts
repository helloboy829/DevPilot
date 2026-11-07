import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test.describe("UI polish mobile regressions", () => {
  test("workspace exposes mobile sidebar navigation from the chat header", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    await page.getByRole("button", { name: /toggle sidebar/i }).click();

    // Creation lives in the conversation page, not a route-dependent global row.
    await expect(
      page.getByRole("link", { name: "Chats", exact: true }),
    ).toBeVisible();
    await expect(
      page.locator("[data-sidebar='sidebar'] a[href='/workspace/chats/new']"),
    ).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Custom assistants", exact: true }),
    ).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(375);
  });

  test("mobile artifacts open in a drawer without horizontal overflow", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Thread with artifact",
          artifacts: ["reports/mobile-summary.md"],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.getByTestId("artifact-trigger").click();

    await expect(
      page.getByRole("dialog", { name: /artifacts/i }),
    ).toBeVisible();
    await expect(page.getByText("mobile-summary.md")).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(375);
  });

  test("global focus ring tokens are visible in light and dark themes", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.goto("/workspace/chats/new");

    const readRing = () =>
      page.evaluate(() =>
        getComputedStyle(document.documentElement)
          .getPropertyValue("--ring")
          .trim(),
      );

    // Exercise the hydrated theme controller rather than racing its initial
    // effect by mutating <html> directly.
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await sidebar.getByRole("button", { name: /Settings and more/ }).click();
    await page.getByRole("menuitem", { name: "Settings", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Settings", exact: true });
    await dialog.getByRole("button", { name: /^Light\b/ }).click();
    await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
    const lightRing = await readRing();
    expect(lightRing).not.toBe("transparent");
    expect(lightRing).not.toBe("");

    await dialog.getByRole("button", { name: /^Dark\b/ }).click();
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    const darkRing = await readRing();
    expect(darkRing).not.toBe("transparent");
    expect(darkRing).not.toBe("");

    // The two themes must resolve to different ring tokens, otherwise the test
    // would pass trivially if <html> were stuck in one mode.
    expect(darkRing).not.toBe(lightRing);
  });
});
