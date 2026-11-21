import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("material batches show the frozen component denominator and safe file status", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/evaluation/material-batches*", (route) =>
    route.fulfill({
      json: {
        batches: [
          {
            id: "batch-1",
            name: "Synthetic intake",
            status: "open",
            component_count: 2,
            created_at: "2026-11-22T10:00:00Z",
            updated_at: "2026-11-22T10:00:00Z",
            archived_at: null,
          },
        ],
      },
    }),
  );
  await page.route("**/api/evaluation/material-batches/batch-1", (route) =>
    route.fulfill({
      json: {
        id: "batch-1",
        name: "Synthetic intake",
        status: "open",
        component_count: 2,
        created_at: "2026-11-22T10:00:00Z",
        updated_at: "2026-11-22T10:00:00Z",
        archived_at: null,
        components: [
          {
            component_id: "search",
            name: "Search assistant",
            kind: "agent",
            purpose: "Synthetic retrieval checks",
            status: "pending",
            reason: null,
            artifact_ids: ["material-1"],
          },
          {
            component_id: "vision",
            name: "Vision model",
            kind: "cv",
            purpose: "Synthetic image checks",
            status: "pending",
            reason: null,
            artifact_ids: [],
          },
        ],
        artifacts: [
          {
            id: "material-1",
            file_name: "fixture.txt",
            authorization_basis: "user_provided",
            purpose: "Synthetic fixture",
            sensitivity: "internal",
            retention_until: "2026-12-01T00:00:00Z",
            status: "uploaded",
            sha256: "a".repeat(64),
            size_bytes: 12,
            created_at: "2026-11-22T10:00:00Z",
            uploaded_at: "2026-11-22T10:01:00Z",
            parse_status: "pending",
            parser_version: null,
            parse_result_hash: null,
            parse_block_count: null,
            parse_reason: null,
            parsed_at: null,
          },
        ],
      },
    }),
  );

  await page.goto("/workspace/material-batches");

  await page
    .getByRole("button", { name: "Open batch Synthetic intake" })
    .click();
  await expect(page.getByText("Frozen denominator")).toBeVisible();
  await expect(page.getByText("Frozen denominator: 2 / 2")).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "Search assistant" }),
  ).toBeVisible();
  await expect(page.getByRole("cell", { name: "Vision model" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "fixture.txt" })).toBeVisible();
  await expect(page.getByText("uploaded", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "pending" })).toHaveCount(3);
  await expect(page.getByText("a".repeat(64))).toHaveCount(0);
});
