import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const run = "1".repeat(32);
const assessment = "b".repeat(32);
const hash = "c".repeat(64);
const approver = "00000000-0000-0000-0000-000000000005";

async function setup(page: Page) {
  mockLangGraphAPI(page, { threads: [] });
  const reads: string[] = [];
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({
      json: { projects: [{ id: "p1", name: "Synthetic project" }] },
    }),
  );
  await page.route("**/api/evaluation/projects/p1/datasets", (route) =>
    route.fulfill({ json: { datasets: [] } }),
  );
  await page.route("**/api/evaluation/projects/p1/components", (route) =>
    route.fulfill({ json: { components: [] } }),
  );
  await page.route("**/api/evaluation/projects/p1/approvals", (route) => {
    reads.push(route.request().url());
    return route.fulfill({ json: [] });
  });
  await page.goto("/workspace/datasets");
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p1");
  return {
    panel: page.getByRole("region", { name: "Formal approvals" }),
    reads,
  };
}

test("approval panel reads only after an explicit click and shows metadata", async ({
  page,
}) => {
  const { panel, reads } = await setup(page);
  const forbidden: string[] = [];
  page.on("request", (request) => {
    if (/\/(references|open|execute|debug\/send)/.test(request.url()))
      forbidden.push(request.url());
  });
  await expect(panel).toBeVisible();
  expect(reads).toEqual([]);
  await panel
    .getByRole("button", { name: "Load project approvals", exact: true })
    .click();
  await expect(
    panel.getByText("No approvals in this project yet."),
  ).toBeVisible();
  expect(reads).toHaveLength(1);
  await expect(page.locator("body")).not.toContainText("SYNTHETIC_GOLD");
  expect(forbidden).toEqual([]);
});

test("preflight shows fixed blockers without writing or reading evidence", async ({
  page,
}) => {
  const { panel } = await setup(page);
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && request.url().includes("/approval"))
      writes.push(request.url());
  });
  let preflightUrl = "";
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/assessments/*/approval-preflight*",
    (route) => {
      preflightUrl = route.request().url();
      return route.fulfill({
        json: {
          schema: "qa-approval-preflight.v1",
          scope: "read_only_formal_approval_preflight",
          project_id: "p1",
          run_id: run,
          assessment: { id: assessment, revision: 1, assessment_hash: hash },
          approver_id: approver,
          eligible: false,
          blockers: ["criteria_not_met"],
          readiness: "review_complete",
          criteria: { status: "not_met" },
          separation: {
            approver_not_owner: true,
            approver_not_review_actor: true,
          },
          latest_approval: null,
          approval: "not_recorded",
        },
      });
    },
  );
  await panel.getByLabel("Run ID", { exact: true }).fill(run);
  await panel.getByLabel("Assessment ID", { exact: true }).fill(assessment);
  await panel.getByLabel("Assessment hash", { exact: true }).fill(hash);
  await panel.getByLabel("Approver account", { exact: true }).fill(approver);
  await panel
    .getByRole("button", { name: "Check approval eligibility", exact: true })
    .click();
  await expect(panel.getByText(/Blocked: criteria_not_met/)).toBeVisible();
  expect(preflightUrl).toContain(`approver_id=${approver}`);
  expect(preflightUrl).toContain(
    `/assessments/${assessment}/approval-preflight`,
  );
  expect(writes).toEqual([]);
});

test("checks approval chain integrity read-only and shows fixed blockers", async ({
  page,
}) => {
  const { panel } = await setup(page);
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && request.url().includes("/approval"))
      writes.push(request.url());
  });
  let reads = 0;
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/approvals/integrity",
    (route) => {
      reads += 1;
      return route.fulfill({
        json: {
          schema: "qa-approval-chain.v1",
          scope: "approval_audit_chain_only",
          status: "broken",
          approvals: 2,
          events: 1,
          blockers: ["event_count_mismatch"],
        },
      });
    },
  );
  await panel.getByLabel("Run ID", { exact: true }).fill(run);
  expect(reads).toBe(0);
  await panel
    .getByRole("button", {
      name: "Check approval chain integrity",
      exact: true,
    })
    .click();
  await expect(
    panel.getByText("Chain broken: event_count_mismatch"),
  ).toBeVisible();
  expect(reads).toBe(1);
  expect(writes).toEqual([]);
  await expect(page.locator("body")).not.toContainText("approval_hash");
});

test("records an explicit approval with a generated original ID", async ({
  page,
}) => {
  const { panel } = await setup(page);
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/approvals/audit",
    (route) => route.fulfill({ json: [] }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/approvals",
    (route) => route.fulfill({ json: [] }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/approvals/*",
    (route) => {
      if (route.request().method() !== "POST")
        return route.fulfill({ json: [] });
      writes.push({
        url: route.request().url(),
        body: route.request().postDataJSON(),
      });
      return route.fulfill({
        json: {
          id: "d".repeat(32),
          revision: 1,
          decision: "approved",
          approver_id: approver,
        },
      });
    },
  );
  await panel.getByLabel("Run ID", { exact: true }).fill(run);
  await panel.getByLabel("Assessment ID", { exact: true }).fill(assessment);
  await panel.getByLabel("Assessment hash", { exact: true }).fill(hash);
  await panel.getByLabel("Approver account", { exact: true }).fill(approver);
  await panel
    .getByRole("button", { name: "Load run approvals and audit", exact: true })
    .click();
  await expect(panel.getByText("No approvals for this run yet.")).toBeVisible();
  await panel.getByRole("checkbox").check();
  await panel
    .getByRole("button", { name: "Record approval / revocation", exact: true })
    .click();
  await expect(
    panel.getByText(/Recorded revision 1 \(approved\)/),
  ).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0]!.url).toMatch(/\/approvals\/[0-9a-f]{32}$/);
  expect(writes[0]!.body).toEqual({
    assessment_id: assessment,
    assessment_hash: hash,
    expected_previous_revision: 0,
    approver_id: approver,
    decision: "approved",
    confirmed: true,
  });
});

test("keeps an unknown write on the same ID without retry", async ({
  page,
}) => {
  const { panel } = await setup(page);
  const writes: string[] = [];
  let posts = 0;
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/approvals/audit",
    (route) => route.fulfill({ json: [] }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/approvals",
    (route) => route.fulfill({ json: [] }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/approvals/*",
    (route) => {
      if (route.request().method() !== "POST")
        return route.fulfill({ json: [] });
      posts += 1;
      writes.push(route.request().url());
      return route.fulfill({ status: 503, json: { detail: "unknown" } });
    },
  );
  await panel.getByLabel("Run ID", { exact: true }).fill(run);
  await panel.getByLabel("Assessment ID", { exact: true }).fill(assessment);
  await panel.getByLabel("Assessment hash", { exact: true }).fill(hash);
  await panel.getByLabel("Approver account", { exact: true }).fill(approver);
  await panel.getByRole("checkbox").check();
  await panel
    .getByRole("button", { name: "Record approval / revocation", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toBeVisible();
  expect(posts).toBe(1);
  const id = writes[0]!.split("/").pop();
  expect(id).toMatch(/^[0-9a-f]{32}$/);
  await expect(panel.getByRole("status")).toContainText(id!);
});
