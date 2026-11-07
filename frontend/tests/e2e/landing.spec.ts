import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Landing page", () => {
  test("renders the header and hero section", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.locator("header").first().getByText("DevPilot", { exact: true }),
    ).toBeVisible();
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toContainText("DevPilot");
    await expect(
      page.getByRole("region", { name: "Evaluation workflow" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /02 \/ Schedule evaluations/ }),
    ).toHaveAttribute("href", "/workspace/evaluation-schedules");

    // "Open DevPilot" call-to-action button in hero
    await expect(
      page.getByRole("link", { name: /open devpilot/i }),
    ).toBeVisible();
  });

  for (const width of [320, 375, 390]) {
    test(`does not overflow at ${width}px width`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto("/");

      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width);
      await expect(page.locator("main").first()).toBeInViewport();
    });
  }

  test("Open DevPilot link navigates to workspace", async ({ page }) => {
    mockLangGraphAPI(page);
    await page.route("**/api/component-tests/components*", (route) =>
      route.fulfill({ json: { components: [] } }),
    );

    await page.goto("/");

    const getStarted = page.getByRole("link", { name: /open devpilot/i });
    await getStarted.click();

    // The product entry is evaluation-first; chat remains a secondary route.
    await page.waitForURL("**/workspace/evaluations");
    await expect(page).toHaveURL(/\/workspace\/evaluations/);
    await expect(
      page.getByRole("heading", { name: "Evaluation workbench", exact: true }),
    ).toBeVisible();
  });
});
