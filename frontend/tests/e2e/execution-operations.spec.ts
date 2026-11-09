import { expect, test } from "@playwright/test";

import fixture from "../fixtures/reservation-snapshot";

import { mockLangGraphAPI } from "./utils/mock-api";

const endpoint = "**/api/evaluation/operations/reservations";
for (const mobile of [false, true]) {
  test(`admin diagnostic manual-only navigation and privacy (${mobile ? "mobile" : "desktop"})`, async ({
    page,
  }) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page);
    const requests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/evaluation/"))
        requests.push(r.method() + " " + new URL(r.url()).pathname);
    });
    await page.route(endpoint, (route) => route.fulfill({ json: fixture }));
    await page.goto("/workspace/operations");
    const load = page.getByRole("button", {
      name: "Load reservation snapshot",
    });
    await expect(load).toBeVisible();
    expect(requests).toEqual([]);
    await load.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("reservation-snapshot")).toBeVisible();
    await expect(page.getByText("70", { exact: true })).toBeVisible();
    await expect(
      page.getByText(/A reached deadline does not prove/),
    ).toBeVisible();
    await expect(
      page.getByText(/not global agreement or available quota/),
    ).toBeVisible();
    expect(requests).toEqual(["GET /api/evaluation/operations/reservations"]);
    const stored = await page.evaluate(() =>
      JSON.stringify({
        local: { ...localStorage },
        session: { ...sessionStorage },
      }),
    );
    expect(stored).not.toContain("execution_reservations_diagnostic_only");
    expect(stored).not.toContain("1700000000000");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    if (mobile)
      await page.locator("[data-sidebar='trigger']:visible").first().click();
    const sidebar = page.locator(
      mobile
        ? "[data-mobile='true'][data-sidebar='sidebar']"
        : "[data-sidebar='sidebar']",
    );
    const entry = sidebar.locator("a[href='/workspace/operations']");
    await expect(entry).toHaveCount(1);
    await expect(entry).toHaveAttribute("data-active", "true");
    await expect(sidebar.locator("a[href='/workspace/chats/new']")).toHaveCount(
      0,
    );
    await sidebar
      .getByRole("link", { name: "Evaluation workbench", exact: true })
      .click();
    if (mobile)
      await page.locator("[data-sidebar='trigger']:visible").first().click();
    await expect(entry).toHaveCount(1);
    await entry.click();
    await expect(page.getByTestId("reservation-snapshot")).toHaveCount(0);
    expect(requests).toEqual(["GET /api/evaluation/operations/reservations"]);
  });
}
test("Chinese workspace rejects extra sensitive fields without automatic retry", async ({
  page,
  context,
  baseURL,
}) => {
  if (!baseURL) throw new Error("baseURL required");
  await context.addCookies([{ name: "locale", value: "zh-CN", url: baseURL }]);
  mockLangGraphAPI(page);
  let calls = 0;
  await page.route(endpoint, (route) => {
    calls++;
    return route.fulfill({ json: { ...fixture, owner_id: "SECRET-SENTINEL" } });
  });
  await page.goto("/workspace/operations");
  await expect(
    page.getByRole("heading", { name: "执行预留诊断", exact: true }),
  ).toBeVisible();
  expect(calls).toBe(0);
  await page.getByRole("button", { name: "手动加载预留快照" }).click();
  await expect(
    page.getByRole("region", { name: "执行预留只读诊断" }).getByRole("alert"),
  ).toContainText("未自动重试");
  await expect(page.getByText("SECRET-SENTINEL")).toHaveCount(0);
  await expect(page.getByTestId("reservation-snapshot")).toHaveCount(0);
  expect(calls).toBe(1);
});
test("role refresh hides the stable admin entry and fences a late diagnostic response", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  let calls = 0;
  let deliver!: () => void;
  const gate = new Promise<void>((yes) => {
    deliver = yes;
  });
  await page.route(endpoint, async (route) => {
    calls++;
    await gate;
    await route.fulfill({ json: fixture }).catch(() => undefined);
  });
  await page.goto("/workspace/operations");
  await page.getByRole("button", { name: "Load reservation snapshot" }).click();
  await expect.poll(() => calls).toBe(1);
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "default",
        email: "synthetic@test.local",
        system_role: "user",
        needs_setup: false,
      },
    }),
  );
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await expect(page.getByText(/Administrators only/)).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Workspace navigation" })
      .locator("a[href='/workspace/operations']"),
  ).toHaveCount(0);
  deliver();
  await expect(page.getByTestId("reservation-snapshot")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Load reservation snapshot" }),
  ).toHaveCount(0);
  expect(calls).toBe(1);
});
