import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Sidebar navigation", () => {
  test("sidebar contains conversation and custom assistant links", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    // Sidebar uses data-sidebar="menu-button" with asChild rendering on <Link>
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.locator("a[href='/workspace/chats']")).toBeVisible({
      timeout: 15_000,
    });
    await expect(sidebar.locator("a[href='/workspace/agents']")).toBeVisible();
  });

  test("Agents link navigates to agents page", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const agentsLink = sidebar.locator("a[href='/workspace/agents']");
    await expect(agentsLink).toBeVisible({ timeout: 15_000 });
    await agentsLink.click();

    await page.waitForURL("**/workspace/agents");
    await expect(page).toHaveURL(/\/workspace\/agents/);
    await expect(
      page.getByRole("heading", { name: "Custom assistants", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(/They are not approved test executors/),
    ).toBeVisible();
  });

  test("disabled custom assistants are absent, not dead navigation", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.route("**/api/features", (route) =>
      route.fulfill({ json: { agents_api: { enabled: false } } }),
    );
    const features = page.waitForResponse("**/api/features");
    await page.goto("/workspace/evaluations");
    await features;
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.locator("a[href='/workspace/chats']")).toBeVisible();
    await expect(sidebar.locator("a[href='/workspace/agents']")).toHaveCount(0);
    await expect(
      sidebar.getByRole("button", { name: /Agents|Custom assistants/ }),
    ).toHaveCount(0);
  });

  for (const mobile of [false, true]) {
    test(
      "evaluation sidebar has exactly one component test entry (" +
        (mobile ? "mobile" : "desktop") +
        ")",
      async ({ page }) => {
        if (mobile) await page.setViewportSize({ width: 390, height: 844 });
        mockLangGraphAPI(page);
        await page.goto("/workspace/evaluations");
        if (mobile)
          await page
            .locator("[data-sidebar='trigger']:visible")
            .first()
            .click();
        const sidebar = page.locator(
          mobile
            ? "[data-mobile='true'][data-sidebar='sidebar']"
            : "[data-sidebar='sidebar']",
        );
        await expect(
          sidebar.locator("a[href='/workspace/component-tests']"),
        ).toHaveCount(1);
        await expect(
          sidebar.locator("a[href='/workspace/chats/new']"),
        ).toHaveCount(0);
        const entry = sidebar.locator("a[href='/workspace/component-tests']");
        await entry.click();
        await expect(page).toHaveURL(/\/workspace\/component-tests/);
        if (mobile) await expect(sidebar).toBeHidden();
        if (mobile)
          await page
            .locator("[data-sidebar='trigger']:visible")
            .first()
            .click();
        await expect(entry).toHaveAttribute("data-active", "true");
      },
    );
  }

  test("Chinese evaluation navigation uses one component-test label", async ({
    page,
    context,
    baseURL,
  }) => {
    mockLangGraphAPI(page);
    if (!baseURL) throw new Error("Playwright baseURL is required");
    await context.addCookies([
      { name: "locale", value: "zh-CN", url: baseURL },
    ]);
    await page.goto("/workspace/evaluations");
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(
      sidebar.getByRole("link", { name: "组件测试", exact: true }),
    ).toHaveCount(1);
    await expect(
      sidebar.getByRole("link", { name: "自定义助手", exact: true }),
    ).toBeVisible();
  });

  test("mobile welcome layout stays within viewport and opens sidebar", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const viewportWidth = page.viewportSize()?.width ?? 390;
    const expectInsideViewport = async (
      locator: ReturnType<typeof page.locator>,
    ) => {
      await expect(locator).toBeVisible({ timeout: 15_000 });
      const box = await locator.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(-1);
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewportWidth + 1);
    };

    await expectInsideViewport(page.getByText(/Welcome to|欢迎使用/).first());
    await expectInsideViewport(page.getByRole("textbox").first());
    await expectInsideViewport(page.locator("[data-slot='suggestions-list']"));

    const mobileSidebarTrigger = page
      .locator("[data-sidebar='trigger']:visible")
      .first();
    await expect(mobileSidebarTrigger).toBeVisible();
    await mobileSidebarTrigger.click();

    const mobileSidebar = page.locator(
      "[data-mobile='true'][data-sidebar='sidebar']",
    );
    await expect(mobileSidebar).toBeVisible();
    await expect(
      mobileSidebar.locator("a[href='/workspace/chats']"),
    ).toBeVisible();
    await expect(
      mobileSidebar.locator("a[href='/workspace/agents']"),
    ).toBeVisible();
  });
});
