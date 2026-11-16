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
      if (route.request().method() !== "POST") return route.fallback();
      writes.push({
        url: route.request().url(),
        body: route.request().postDataJSON(),
      });
      return route.fulfill({
        json: {
          schema: "qa-run-formal-approval.v1",
          scope: "formal_approval_decision",
          id: route.request().url().split("/").pop(),
          project_id: "p1",
          run_id: run,
          revision: 1,
          created_at_ms: 1,
          recorded_by: "owner",
          policy: {
            id: "independent-double-blind.v1",
            population: "all_frozen_effectiveness_samples",
            source: "immutable_independent_assessment",
            separation: "approver_not_owner_or_independent_reviewer",
          },
          assessment: {
            id: assessment,
            revision: 1,
            assessment_hash: hash,
            summary_hash: "e".repeat(64),
          },
          counts: { pass: 2, fail: 0, uncertain: 0, unreviewed: 0 },
          technical_counts: { collected: 2 },
          human_pass_rate: { numerator: 2, denominator: 2, value: 1 },
          criteria: { status: "not_defined", approval: "not_approved" },
          readiness: "review_complete",
          decision: "approved",
          approver_id: approver,
          note: null,
          approval_hash: "f".repeat(64),
        },
      });
    },
  );
  await panel
    .getByRole("button", { name: "Load project approvals", exact: true })
    .click();
  await expect(
    panel.getByText("No approvals in this project yet."),
  ).toBeVisible();
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
  await expect(panel.getByLabel("Approval run", { exact: true })).toContainText(
    `${run} · r1 approved`,
  );
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
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/assessments/*/approval-preflight*",
    (route) =>
      route.fulfill({
        json: {
          schema: "qa-approval-preflight.v1",
          scope: "read_only_formal_approval_preflight",
          project_id: "p1",
          run_id: run,
          assessment: { id: assessment, revision: 1, assessment_hash: hash },
          approver_id: approver,
          eligible: true,
          blockers: [],
          readiness: "review_complete",
          criteria: { status: "not_defined" },
          separation: {
            approver_not_owner: true,
            approver_not_review_actor: true,
          },
          latest_approval: null,
          approval: "not_recorded",
        },
      }),
  );
  await panel
    .getByRole("button", { name: "Check approval eligibility", exact: true })
    .click();
  await expect(
    panel.getByText(/Eligible \(explicit confirmation/),
  ).toBeVisible();
  await panel.getByRole("checkbox").check();
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/approvals",
    (route) =>
      route.fulfill({
        json: [
          {
            id,
            project_id: "p1",
            run_id: run,
            revision: 1,
            created_at_ms: 1,
            assessment_id: assessment,
            assessment_hash: hash,
            approver_id: approver,
            decision: "approved",
            approval_hash: "f".repeat(64),
          },
        ],
      }),
  );
  await page.route(
    `**/api/evaluation/projects/p1/review-runs/${run}/approvals/${id}/metadata`,
    (route) =>
      route.fulfill({
        json: {
          id,
          project_id: "p1",
          run_id: run,
          revision: 1,
          created_at_ms: 1,
          assessment_id: assessment,
          assessment_hash: hash,
          approver_id: approver,
          decision: "approved",
          approval_hash: "f".repeat(64),
        },
      }),
  );
  await panel
    .getByRole("button", {
      name: "Load run approvals and audit",
      exact: true,
    })
    .click();
  await expect(panel.getByText(/revision 1 · approved/)).toBeVisible();
  await expect(panel.getByRole("status")).toHaveCount(0);
  await expect(panel.getByRole("checkbox")).not.toBeChecked();
  await expect(
    panel.getByRole("button", {
      name: "Record approval / revocation",
      exact: true,
    }),
  ).toBeDisabled();
  expect(posts).toBe(1);
});

test("checks the project approval chain summary read-only", async ({
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
    "**/api/evaluation/projects/p1/approvals/integrity",
    (route) => {
      reads += 1;
      return route.fulfill({
        json: {
          schema: "qa-approval-chain-summary.v1",
          scope: "project_approval_audit_chains_only",
          status: "verified",
          runs: 2,
          verified_runs: 2,
          broken_runs: 0,
          approvals: 3,
          events: 3,
          blockers: [],
        },
      });
    },
  );
  expect(reads).toBe(0);
  await panel
    .getByRole("button", { name: "Check project approval chains", exact: true })
    .click();
  await expect(
    panel.getByText(
      "Project chains verified: 2 of 2 runs · 3 approvals / 3 events",
    ),
  ).toBeVisible();
  expect(reads).toBe(1);
  expect(writes).toEqual([]);
});

test("checks approver sign-off progress without a policy", async ({ page }) => {
  const { panel } = await setup(page);
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && request.url().includes("/approval"))
      writes.push(request.url());
  });
  let reads = 0;
  let requestedUrl = "";
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/approvals/sign-off**",
    (route) => {
      reads += 1;
      requestedUrl = route.request().url();
      return route.fulfill({
        json: {
          schema: "qa-approval-signoff.v1",
          scope: "approval_signoff_progress_only",
          policy: "not_defined",
          required_distinct_approvers: null,
          revisions: 2,
          distinct_approvers: 2,
          distinct_approved_approvers: 1,
          approved_revisions: 1,
          revoked_revisions: 1,
          latest_revision: 2,
          latest_decision: "revoked",
          multi_level_satisfied: null,
          blockers: [
            "multi_level_policy_not_defined",
            "approver_login_not_implemented",
          ],
          requirement: {
            schema: "qa-signoff-requirement.v1",
            scope: "technical_signoff_requirement_only",
            policy: { defined: true, required_distinct_approvers: 2 },
            observed: {
              distinct_approved_approvers: 1,
              latest_decision: "revoked",
            },
            satisfied: false,
            blockers: ["insufficient_approvers"],
            approval: "not_approved",
          },
        },
      });
    },
  );
  await panel.getByLabel("Run ID", { exact: true }).fill(run);
  await panel
    .getByLabel("Proposed required approvers (advisory)", { exact: true })
    .fill("2");
  expect(reads).toBe(0);
  await panel
    .getByRole("button", {
      name: "Check approver sign-off progress",
      exact: true,
    })
    .click();
  await expect(
    panel.getByText(
      "Sign-off progress: 2 revisions · 2 distinct approvers · latest revoked",
    ),
  ).toBeVisible();
  await expect(panel.getByText(/Policy not defined/)).toBeVisible();
  await expect(panel.getByText("multi_level_policy_not_defined")).toBeVisible();
  await expect(
    panel.getByText(
      "Advisory requirement: not satisfied · insufficient_approvers",
    ),
  ).toBeVisible();
  await expect(panel.getByText(/Advisory only/)).toBeVisible();
  expect(requestedUrl).toContain("required_distinct_approvers=2");
  expect(reads).toBe(1);
  expect(writes).toEqual([]);
});

test("loads pinned assessment metadata for explicit selection", async ({
  page,
}) => {
  const { panel } = await setup(page);
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && request.url().includes("/approval"))
      writes.push(request.url());
  });
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/*/assessments",
    (route) =>
      route.fulfill({
        json: [
          {
            id: assessment,
            project_id: "p1",
            run_id: run,
            revision: 1,
            created_at_ms: 1,
            summary_hash: "e".repeat(64),
            assessment_hash: hash,
          },
        ],
      }),
  );
  await panel.getByLabel("Run ID", { exact: true }).fill(run);
  await panel
    .getByRole("button", { name: "Load run assessments", exact: true })
    .click();
  await panel
    .getByLabel("Assessment revision", { exact: true })
    .selectOption(assessment);
  await expect(panel.getByLabel("Assessment ID", { exact: true })).toHaveValue(
    assessment,
  );
  await expect(
    panel.getByLabel("Assessment hash", { exact: true }),
  ).toHaveValue(hash);
  expect(writes).toEqual([]);
});

test("shows approval capability gaps read-only", async ({ page }) => {
  const { panel } = await setup(page);
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && request.url().includes("/approval"))
      writes.push(request.url());
  });
  let reads = 0;
  await page.route(
    "**/api/evaluation/projects/p1/approvals/capabilities",
    (route) => {
      reads += 1;
      return route.fulfill({
        json: {
          schema: "qa-approval-capabilities.v1",
          scope: "approval_capability_diagnostic_only",
          approver_login: "not_implemented",
          owner_records_on_behalf: true,
          multi_level_policy: "advisory_only",
          multi_level_enforcement: "not_implemented",
          notifications: "not_implemented",
          export: "not_implemented",
          approval: "not_authorized",
          blockers: [
            "approver_login_not_implemented",
            "multi_level_enforcement_not_implemented",
            "notification_not_implemented",
            "approval_export_not_implemented",
          ],
        },
      });
    },
  );
  expect(reads).toBe(0);
  await panel
    .getByRole("button", { name: "Load approval capabilities", exact: true })
    .click();
  await expect(
    panel.getByText(/Approval capabilities: owner records on behalf/),
  ).toBeVisible();
  await expect(panel.getByText("approver_login_not_implemented")).toBeVisible();
  expect(reads).toBe(1);
  expect(writes).toEqual([]);
});
