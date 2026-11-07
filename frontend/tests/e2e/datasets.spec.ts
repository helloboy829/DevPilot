import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("project QA data is imported, reviewed and frozen without browser persistence", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  const project = { id: "p1", name: "Synthetic project" };
  let dataset = {
    id: "d1",
    project_id: "p1",
    name: "Synthetic QA",
    status: "draft",
    purpose: "baseline",
    revision: 1,
    sample_count: 0,
    content_hash: null as string | null,
    source: {
      label: "Fixture",
      reference: "fixture:qa",
      authorization_basis: "Synthetic owned data",
      attested: true,
    },
  };
  const samples = [
    {
      sample_id: "q1",
      input: "Synthetic question",
      expected: "Synthetic reference",
      source_ref: "record:1",
      slice_tag: "default",
    },
  ];
  let created = false;
  await page.route("**/api/evaluation/projects", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({
        name: "Synthetic project",
      });
      created = true;
      await route.fulfill({ json: project });
    } else
      await route.fulfill({ json: { projects: created ? [project] : [] } });
  });
  await page.route("**/api/evaluation/projects/p1/datasets", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON().source.attested).toBe(true);
      await route.fulfill({ json: dataset });
    } else await route.fulfill({ json: { datasets: [] } });
  });
  await page.route(
    "**/api/evaluation/projects/p1/datasets/d1/**",
    async (route) => {
      if (route.request().url().endsWith("/samples")) {
        expect(route.request().method()).toBe("PUT");
        expect(route.request().postDataJSON().revision).toBe(1);
        dataset = {
          ...dataset,
          revision: 2,
          sample_count: 1,
          content_hash: "a".repeat(64),
        };
        await route.fulfill({ json: dataset });
      } else if (route.request().url().endsWith("/references")) {
        await route.fulfill({ json: { samples } });
      } else if (route.request().url().endsWith("/freeze")) {
        expect(route.request().postDataJSON()).toEqual({
          revision: 2,
          content_hash: "a".repeat(64),
          reviewed: true,
        });
        dataset = { ...dataset, revision: 3, status: "frozen" };
        await route.fulfill({ json: dataset });
      } else await route.fulfill({ json: { events: [] } });
    },
  );
  await page.goto("/workspace/datasets");
  await page
    .getByLabel("Project name", { exact: true })
    .fill("Synthetic project");
  await page
    .getByRole("button", { name: "Create project", exact: true })
    .click();
  await page.getByLabel("Dataset name", { exact: true }).fill("Synthetic QA");
  await page.getByLabel("Source label", { exact: true }).fill("Fixture");
  await page.getByLabel("Source reference", { exact: true }).fill("fixture:qa");
  await page
    .getByLabel("Authorization basis", { exact: true })
    .fill("Synthetic owned data");
  await expect(
    page.getByRole("button", { name: "Create dataset", exact: true }),
  ).toBeDisabled();
  await page.getByRole("checkbox", { name: /I confirm the source/ }).check();
  await page
    .getByRole("button", { name: "Create dataset", exact: true })
    .click();
  await page
    .getByLabel("QA import", { exact: true })
    .fill(JSON.stringify(samples));
  await page
    .getByRole("button", { name: "Replace draft samples", exact: true })
    .click();
  await expect(page.getByLabel("QA import", { exact: true })).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Freeze reviewed version", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Load Q / reference / source", exact: true })
    .click();
  await expect(
    page.getByRole("cell", { name: "Synthetic reference", exact: true }),
  ).toBeVisible();
  await page.getByRole("checkbox", { name: /I reviewed all samples/ }).check();
  await page
    .getByRole("button", { name: "Freeze reviewed version", exact: true })
    .click();
  await expect(page.getByTestId("dataset-status")).toHaveText("Frozen");
  await expect(page.getByLabel("QA import", { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(() => JSON.stringify({ ...localStorage })),
  ).not.toContain("Synthetic reference");
});

test("dataset service failure is visible, not an empty successful inventory", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({ status: 503, json: { detail: "Unavailable" } }),
  );
  await page.goto("/workspace/datasets");
  await expect(page.locator("p[role=alert]")).toContainText("Operation failed");
});

test("review consent is revoked after conflicts, edits and version switches", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.setViewportSize({ width: 390, height: 844 });
  const versions = ["d1", "d2"].map((id) => ({
    id,
    project_id: "p1",
    name: id === "d1" ? "QA one" : "QA two",
    status: "draft",
    purpose: "baseline",
    revision: 2,
    sample_count: 1,
    content_hash: "a".repeat(64),
    source: {
      label: "Fixture",
      reference: "fixture:qa",
      authorization_basis: "Synthetic owned data",
      attested: true,
    },
  }));
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({ json: { projects: [{ id: "p1", name: "Fixture" }] } }),
  );
  await page.route("**/api/evaluation/projects/p1/datasets", (route) =>
    route.fulfill({ json: { datasets: versions } }),
  );
  let freezeCalls = 0;
  await page.route(
    "**/api/evaluation/projects/p1/datasets/*/**",
    async (route) => {
      if (route.request().url().endsWith("/freeze")) {
        freezeCalls++;
        await route.fulfill({
          status: 409,
          json: { detail: "Reload revision" },
        });
      } else {
        await route.fulfill({
          json: {
            samples: [
              {
                sample_id: "q1",
                input: "Synthetic question",
                expected: "Synthetic review answer",
                source_ref: "record:1",
                slice_tag: "default",
              },
            ],
          },
        });
      }
    },
  );
  await page.goto("/workspace/datasets");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p1");
  await page.getByRole("button", { name: /QA one/ }).click();
  const load = page.getByRole("button", {
    name: "Load Q / reference / source",
    exact: true,
  });
  const consent = page.getByRole("checkbox", {
    name: /I reviewed all samples/,
  });
  const freeze = page.getByRole("button", {
    name: "Freeze reviewed version",
    exact: true,
  });
  await load.click();
  await consent.check();
  await freeze.click();
  await expect(page.locator("p[role=alert]")).toContainText(
    "revision conflicts",
  );
  await expect(page.getByTestId("dataset-status")).toHaveText("Draft");
  await expect(consent).not.toBeChecked();
  await expect(freeze).toBeDisabled();
  expect(freezeCalls).toBe(1);
  await load.click();
  await consent.check();
  await page.getByLabel("QA import", { exact: true }).fill("[]");
  await expect(consent).not.toBeChecked();
  await expect(freeze).toBeDisabled();
  await expect(
    page.getByRole("cell", { name: "Synthetic review answer", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: /QA two/ }).click();
  await expect(page.getByLabel("QA import", { exact: true })).toHaveValue("");
  await expect(consent).not.toBeChecked();
  await expect(consent).toBeDisabled();
  await load.click();
  await expect(
    page.getByRole("cell", { name: "Synthetic review answer", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "New dataset version", exact: true })
    .click();
  await expect(
    page.getByRole("cell", { name: "Synthetic review answer", exact: true }),
  ).toHaveCount(0);
});
