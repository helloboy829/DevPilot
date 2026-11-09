import { expect, test, type Page } from "@playwright/test";

import {
  activeTask,
  actors,
  blindDecision,
  caseData,
  id,
  ownerTask,
  task,
  taskCase,
  taskResult,
} from "../fixtures/review-task";

import { mockLangGraphAPI } from "./utils/mock-api";

async function expectNoOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    width: window.innerWidth,
    total: document.documentElement.scrollWidth,
    elements: [...document.querySelectorAll("main *")]
      .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(0, 8)
      .map((el) => ({
        tag: el.tagName,
        className: el.className,
        width: el.getBoundingClientRect().width,
      })),
  }));
  expect(overflow.total, JSON.stringify(overflow)).toBeLessThanOrEqual(
    overflow.width + 1,
  );
}

for (const width of [1440, 390]) {
  test(`independent blind review explicitly claims, opens and appends once (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    mockLangGraphAPI(page, { threads: [] });
    let current = task();
    let reads = 0,
      writes = 0,
      outbound = 0;
    await page.route("https://invalid.example/**", async (route) => {
      outbound++;
      await route.abort();
    });
    await page.route("**/api/evaluation/review-tasks**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (request.method() === "POST") {
        writes++;
        const payload = request.postDataJSON();
        expect(payload.expected_revision).toBe(current.revision);
        expect(payload.confirmed).toBe(true);
        if (path.endsWith("/claim")) current = activeTask();
        else {
          expect(path).toBe(
            "/api/evaluation/review-tasks/" + id + "/decisions",
          );
          expect(payload.subject_hash).toBe(current.subject_hash);
          expect(payload.note).toBe("SYNTHETIC_INDEPENDENT_REASON");
          current = task({
            revision: 3,
            status: "in_review",
            assignment: {
              role: "reviewer_1",
              status: "submitted",
              lease_until_ms: null,
            },
          });
        }
        return route.fulfill({ json: current });
      }
      if (path.endsWith("/case")) {
        reads++;
        return route.fulfill({ json: taskCase(current) });
      }
      return route.fulfill({
        json: path.endsWith(id)
          ? current
          : { tasks: [current], offset: 0, limit: 50 },
      });
    });
    await page.goto("/workspace/reviews");
    expect(reads).toBe(0);
    expect(writes).toBe(0);
    await page
      .getByRole("button", { name: "Load / refresh my review tasks" })
      .click();
    await page
      .getByRole("button", { name: "Open task " + id, exact: true })
      .click();
    const detail = page.getByRole("region", {
      name: "Independent review task detail",
      exact: true,
    });
    expect(reads).toBe(0);
    await expect(
      detail.getByRole("button", { name: "Claim task (30 minutes)" }),
    ).toBeDisabled();
    const consent = detail.getByRole("checkbox", {
      name: /I explicitly confirm the next/,
    });
    await consent.focus();
    await page.keyboard.press("Space");
    const claim = detail.getByRole("button", {
      name: "Claim task (30 minutes)",
    });
    await claim.focus();
    await page.keyboard.press("Enter");
    await expect(detail.getByText(/My assignment: active/)).toBeVisible();
    await expect(consent).not.toBeChecked();
    expect(reads).toBe(0);
    await detail
      .getByRole("button", {
        name: "Explicitly open input, output & reference",
      })
      .click();
    await expect(
      detail.getByText("SYNTHETIC_GOLD", { exact: true }),
    ).toBeVisible();
    await expectNoOverflow(page);
    await expect(detail.locator("img")).toHaveCount(0);
    await expect(detail.locator("a")).toHaveCount(0);
    await expect(
      detail.getByRole("region", {
        name: "Blind decisions (arbitration only)",
      }),
    ).toHaveCount(0);
    await detail
      .getByLabel("Independent review reason", { exact: true })
      .fill("SYNTHETIC_INDEPENDENT_REASON");
    await detail.getByRole("radio", { name: "Pass", exact: true }).check();
    const decisionConsent = detail.getByRole("checkbox", {
      name: /I reviewed the current evidence/,
    });
    await decisionConsent.focus();
    await page.keyboard.press("Space");
    const append = detail.getByRole("button", {
      name: "Append independent decision",
      exact: true,
    });
    await append.focus();
    await page.keyboard.press("Enter");
    await expect(detail.getByRole("status")).toContainText(
      "Immutable human decision appended",
    );
    await expect(
      detail.getByText("SYNTHETIC_GOLD", { exact: true }),
    ).toHaveCount(0);
    expect(writes).toBe(2);
    expect(reads).toBe(1);
    expect(outbound).toBe(0);
    const storage = await page.evaluate(() =>
      JSON.stringify({
        local: { ...localStorage },
        session: { ...sessionStorage },
      }),
    );
    expect(storage).not.toContain("SYNTHETIC_");
    await expectNoOverflow(page);
  });
}

test("unknown inline creation retains one task ID across project switches and reconciles by GET only", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 });
  mockLangGraphAPI(page, { threads: [] });
  let createdId = "";
  let creates = 0,
    receiptReads = 0;
  const run = {
    id: "r1",
    component_name: "Synthetic component",
    plan_label: "Synthetic plan",
    status: "recording_finished",
    request_count: 1,
  };
  await page.route("**/api/evaluation/projects", (route) =>
    route.fulfill({
      json: {
        projects: [
          { id: "p1", name: "Synthetic project" },
          { id: "p2", name: "Other project" },
        ],
      },
    }),
  );
  await page.route("**/api/evaluation/projects/*/datasets", (route) =>
    route.fulfill({ json: { datasets: [] } }),
  );
  await page.route("**/api/evaluation/projects/*/review-runs", (route) =>
    route.fulfill({ json: { runs: [run] } }),
  );
  await page.route(
    "**/api/evaluation/projects/p1/review-runs/r1/**",
    (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/cases/1")) return route.fulfill({ json: caseData });
      return route.fulfill({
        json: {
          scope: "human_review_only",
          run,
          cases: [
            {
              ordinal: 1,
              sample_id: "q1",
              state: "observed",
              kind: "output_collected",
              has_output_evidence: true,
              review_revision: 0,
              review_decision: null,
            },
          ],
          counts: { pass: 0, fail: 0, uncertain: 0, unreviewed: 1 },
          offset: 0,
          limit: 100,
        },
      });
    },
  );
  await page.route(
    "**/api/evaluation/projects/p1/review-tasks/*",
    async (route) => {
      creates++;
      createdId = route.request().url().split("/").at(-1)!;
      expect(route.request().postDataJSON()).toEqual({
        run_id: "r1",
        ordinal: 1,
        case_hash: caseData.case_hash,
        reviewer_ids: actors.slice(0, 2),
        arbitrator_id: actors[2],
        share_reference: true,
        confirmed: true,
      });
      await route.abort("failed");
    },
  );
  await page.route("**/api/evaluation/review-tasks/*", (route) => {
    receiptReads++;
    return route.fulfill({ json: ownerTask({ id: createdId }) });
  });
  await page.goto("/workspace/datasets");
  async function openOwnerCase() {
    await page
      .getByRole("combobox", { name: "Select project", exact: true })
      .selectOption("p1");
    const panel = page.getByRole("region", {
      name: "Human result review",
      exact: true,
    });
    await panel
      .getByRole("button", { name: "Load / refresh review runs", exact: true })
      .click();
    await panel
      .getByRole("combobox", { name: "Review run", exact: true })
      .selectOption("r1");
    await panel
      .getByRole("button", { name: "Load cases", exact: true })
      .click();
    await panel.getByRole("button", { name: /Open case 1/ }).click();
  }
  await openOwnerCase();
  const assignment = page.getByRole("region", {
    name: "Assign independent case review",
    exact: true,
  });
  await assignment
    .getByLabel("Blind reviewer 1 account ID", { exact: true })
    .fill(actors[0]);
  await assignment
    .getByLabel("Blind reviewer 2 account ID", { exact: true })
    .fill(actors[1]);
  await assignment
    .getByLabel("Arbitrator account ID", { exact: true })
    .fill(actors[2]);
  await assignment
    .getByRole("checkbox", { name: /I am authorized to share/ })
    .check();
  await assignment
    .getByRole("checkbox", { name: /I explicitly confirm creating/ })
    .check();
  await assignment
    .getByRole("button", {
      name: "Create independent review task",
      exact: true,
    })
    .click();
  await expect(assignment.getByRole("alert")).toBeVisible();
  expect(createdId).toMatch(/^[0-9a-f]{32}$/);
  await page
    .getByRole("combobox", { name: "Select project", exact: true })
    .selectOption("p2");
  await expect(page.getByText("SYNTHETIC_GOLD", { exact: true })).toHaveCount(
    0,
  );
  await openOwnerCase();
  await expect(
    assignment.getByText("Task ID: " + createdId, { exact: true }),
  ).toBeVisible();
  await expect(
    assignment.getByRole("button", {
      name: "Create independent review task",
      exact: true,
    }),
  ).toHaveCount(0);
  await assignment
    .getByRole("button", { name: "Reconcile same task ID (GET)", exact: true })
    .click();
  await expect(assignment.getByText(/Task receipt confirmed/)).toBeVisible();
  await expectNoOverflow(page);
  expect(creates).toBe(1);
  expect(receiptReads).toBe(1);
  const storage = await page.evaluate(() =>
    JSON.stringify({
      local: { ...localStorage },
      session: { ...sessionStorage },
    }),
  );
  expect(storage).not.toContain(createdId);
  expect(storage).not.toContain("SYNTHETIC_");
});

test("owner explicitly opens historical resolutions and reopens without rewriting old decisions", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  let current = ownerTask({ status: "resolved", revision: 5 });
  const rounds: number[] = [];
  let writes = 0;
  await page.route("**/api/evaluation/review-tasks**", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "POST") {
      expect(url.pathname.endsWith("/reopen")).toBe(true);
      expect(request.postDataJSON()).toEqual({
        expected_revision: 5,
        confirmed: true,
        reason: "SYNTHETIC_REOPEN_REASON",
      });
      writes++;
      current = ownerTask({ round: 2, revision: 6 });
      return route.fulfill({ json: current });
    }
    if (url.pathname.endsWith("/result")) {
      const round = Number(url.searchParams.get("round_number"));
      rounds.push(round);
      return route.fulfill({ json: taskResult(current, round) });
    }
    return route.fulfill({
      json: url.pathname.endsWith(id)
        ? current
        : { tasks: [current], offset: 0, limit: 50 },
    });
  });
  await page.goto("/workspace/reviews");
  await page.getByLabel("Look up task ID", { exact: true }).fill(id);
  await page
    .getByRole("button", { name: "Open task metadata by ID", exact: true })
    .click();
  const detail = page.getByRole("region", {
    name: "Independent review task detail",
    exact: true,
  });
  expect(rounds).toHaveLength(0);
  await detail
    .getByRole("button", {
      name: "Explicitly open round result & reasons",
      exact: true,
    })
    .click();
  await expect(
    detail.getByRole("region", { name: "Verified historical case resolution" }),
  ).toContainText("SYNTHETIC_BLIND_REASON_reviewer_1");
  await detail
    .getByLabel("Reopen reason", { exact: true })
    .fill("SYNTHETIC_REOPEN_REASON");
  await detail
    .getByRole("checkbox", { name: /I explicitly confirm the next/ })
    .check();
  await detail
    .getByRole("button", {
      name: "Reopen in a new round (retain history)",
      exact: true,
    })
    .click();
  await expect(detail.getByRole("status")).toContainText(
    "Task action confirmed",
  );
  await detail.getByLabel("Result round", { exact: true }).fill("1");
  await detail
    .getByRole("button", {
      name: "Explicitly open round result & reasons",
      exact: true,
    })
    .click();
  await expect(
    detail.getByRole("region", { name: "Verified historical case resolution" }),
  ).toContainText("SYNTHETIC_BLIND_REASON_reviewer_1");
  expect(writes).toBe(1);
  expect(rounds).toEqual([1, 1]);
});

test("only escalated arbitration explicitly opens both blind decisions and keeps uncertainty unresolved", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 });
  mockLangGraphAPI(page, { threads: [] });
  let current = task({
    role: "arbitrator",
    status: "escalated",
    revision: 5,
    assignment: { role: "arbitrator", status: "offered", lease_until_ms: null },
  });
  let opens = 0,
    writes = 0;
  await page.route("**/api/evaluation/review-tasks**", (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    if (request.method() === "POST") {
      writes++;
      expect(request.postDataJSON().expected_revision).toBe(current.revision);
      if (path.endsWith("/claim"))
        current = {
          ...current,
          revision: 6,
          assignment: {
            role: "arbitrator",
            status: "active",
            lease_until_ms: Date.now() + 1_800_000,
          },
        };
      else {
        expect(path.endsWith("/decisions")).toBe(true);
        expect(request.postDataJSON()).toEqual({
          expected_revision: 6,
          subject_hash: current.subject_hash,
          decision: "uncertain",
          note: "SYNTHETIC_ARBITRATION_UNCERTAIN",
          confirmed: true,
        });
        current = {
          ...current,
          revision: 7,
          assignment: {
            role: "arbitrator",
            status: "submitted",
            lease_until_ms: null,
          },
        };
      }
      return route.fulfill({ json: current });
    }
    if (path.endsWith("/case")) {
      opens++;
      return route.fulfill({
        json: taskCase(current, {
          prior_decisions: [
            blindDecision("reviewer_1"),
            blindDecision("reviewer_2", "fail"),
          ],
        }),
      });
    }
    return route.fulfill({ json: { tasks: [current], offset: 0, limit: 50 } });
  });
  await page.goto("/workspace/reviews");
  await page
    .getByRole("button", { name: "Load / refresh my review tasks" })
    .click();
  await page
    .getByRole("button", { name: "Open task " + id, exact: true })
    .click();
  const detail = page.getByRole("region", {
    name: "Independent review task detail",
    exact: true,
  });
  expect(opens).toBe(0);
  await detail
    .getByRole("checkbox", { name: /I explicitly confirm the next/ })
    .check();
  await detail.getByRole("button", { name: "Claim task (30 minutes)" }).click();
  await expect(detail.getByText(/My assignment: active/)).toBeVisible();
  await detail
    .getByRole("button", { name: "Explicitly open input, output & reference" })
    .click();
  const prior = detail.getByRole("region", {
    name: "Blind decisions (arbitration only)",
  });
  await expect(prior).toContainText("SYNTHETIC_BLIND_REASON_reviewer_1");
  await expect(prior).toContainText("SYNTHETIC_BLIND_REASON_reviewer_2");
  await detail
    .getByLabel("Independent review reason", { exact: true })
    .fill("SYNTHETIC_ARBITRATION_UNCERTAIN");
  await expect(
    detail.getByRole("radio", {
      name: "Insufficient / uncertain",
      exact: true,
    }),
  ).toBeChecked();
  await detail
    .getByRole("checkbox", { name: /I reviewed the current evidence/ })
    .check();
  await detail
    .getByRole("button", { name: "Append independent decision", exact: true })
    .click();
  await expect(detail.getByRole("status")).toContainText(
    "Immutable human decision appended",
  );
  await expect(detail).toContainText("escalated");
  expect(opens).toBe(1);
  expect(writes).toBe(2);
  await expectNoOverflow(page);
});
