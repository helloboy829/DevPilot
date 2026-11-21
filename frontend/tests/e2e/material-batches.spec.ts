import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("material batches show the frozen component denominator and safe file status", async ({
  page,
}) => {
  let previewRequests = 0;
  let receiptRequests = 0;
  let forceUnknownPreview = false;
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
  await page.route(
    "**/api/evaluation/material-batches/batch-1/attachments/material-1/preview",
    async (route) => {
      previewRequests++;
      const payload = route.request().postDataJSON();
      expect(payload.open_content).toBe(true);
      expect(payload.operation_id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      );
      if (forceUnknownPreview) {
        await route.fulfill({ status: 503, json: { detail: "Unavailable" } });
        return;
      }
      await route.fulfill({
        headers: { "Cache-Control": "private, no-store" },
        json: {
          operation_id: payload.operation_id,
          parse_status: "parsed",
          parser_version: "material-parser.v1",
          blocks: [
            { text: "SYNTHETIC_PREVIEW_BODY", source_location: "line 1" },
          ],
          reason: null,
          result_hash: "b".repeat(64),
        },
      });
    },
  );
  await page.route(
    "**/api/evaluation/material-batches/previews/*",
    async (route) => {
      receiptRequests++;
      const operationId = new URL(route.request().url()).pathname
        .split("/")
        .at(-1);
      await route.fulfill({
        headers: { "Cache-Control": "private, no-store" },
        json: {
          operation_id: operationId,
          parse_status: "parsed",
          parser_version: "material-parser.v1",
          result_hash: "c".repeat(64),
          block_count: 1,
          reason: null,
          created_at: "2026-11-22T10:05:00Z",
        },
      });
    },
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
  await expect(page.getByRole("cell", { name: "pending" })).toHaveCount(3);
  await page.getByRole("button", { name: "Preview parsed content" }).click();
  await expect(page.getByText(/preview.*content/i)).toBeVisible();
  await expect.poll(() => previewRequests).toBe(0);
  await page.getByRole("button", { name: "Open content once" }).click();
  await expect(page.getByText("SYNTHETIC_PREVIEW_BODY")).toBeVisible();
  expect(previewRequests).toBe(1);
  await expect(page.getByText("uploaded", { exact: true })).toBeVisible();
  await expect(page.getByText("a".repeat(64))).toHaveCount(0);
  await page.getByRole("button", { name: "Close and clear content" }).click();
  await expect(page.getByText("SYNTHETIC_PREVIEW_BODY")).toHaveCount(0);
  forceUnknownPreview = true;
  await page.getByRole("button", { name: "Preview parsed content" }).click();
  await page.getByRole("button", { name: "Open content once" }).click();
  await expect(
    page.getByText(/Receipt recorded: parsed, 1 blocks/),
  ).toBeVisible();
  expect(previewRequests).toBe(2);
  expect(receiptRequests).toBe(1);
  await expect(page.getByText("SYNTHETIC_PREVIEW_BODY")).toHaveCount(0);
});
