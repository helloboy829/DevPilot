import {
  expect,
  request,
  test,
  type BrowserContext,
  type Page,
} from "@playwright/test";

const APP =
  process.env.E2E_APPROVAL_APP_URL ??
  `http://localhost:${process.env.E2E_APPROVAL_FRONTEND_PORT ?? "3012"}`;
const REQUEST_ID = "d".repeat(32);
const RUN_ID = "a".repeat(32);
const ASSESSMENT_ID = "c".repeat(32);
const ASSESSMENT_HASH = "1".repeat(64);
const SUBJECT_HASH = "2".repeat(64);
const SUMMARY_HASH = "4".repeat(64);
const VIEW_HASH = "3".repeat(64);
const PASSWORD = "Synthetic-e2e-password-123!";

type RequestStatus = "pending" | "approved" | "revoked" | "cancelled";
type RequestReceipt = {
  schema: "qa-approval-request.v1";
  id: string;
  project_id: string;
  run_id: string;
  assessment_id: string;
  assessment_hash: string;
  approver_id: string;
  created_at_ms: number;
  expires_at_ms: number;
  subject_hash: string;
  revision: number;
  status: RequestStatus;
  latest_approval_id: string | null;
};

async function registerOrdinaryUser(context: BrowserContext) {
  const email = `approval-e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  const registered = await context.request.post(`${APP}/api/v1/auth/register`, {
    data: { email, password: PASSWORD },
  });
  expect(registered.status(), await registered.text()).toBe(201);

  const response = await context.request.get(`${APP}/api/v1/auth/me`);
  expect(response.status(), await response.text()).toBe(200);
  const user = (await response.json()) as {
    id: string;
    email: string;
    system_role: string;
    needs_setup: boolean;
  };
  expect(user.email).toBe(email);
  expect(user.system_role).toBe("user");
  expect(user.needs_setup).toBe(false);
  return user;
}

function makeRequest(userId: string): RequestReceipt {
  const now = Date.now();
  return {
    schema: "qa-approval-request.v1",
    id: REQUEST_ID,
    project_id: "synthetic-project",
    run_id: RUN_ID,
    assessment_id: ASSESSMENT_ID,
    assessment_hash: ASSESSMENT_HASH,
    approver_id: userId,
    created_at_ms: now - 1000,
    expires_at_ms: now + 86_400_000,
    subject_hash: SUBJECT_HASH,
    revision: 1,
    status: "pending",
    latest_approval_id: null,
  };
}

function makeState(request: RequestReceipt) {
  return {
    schema: "qa-approval-request-state.v1",
    request,
    approval_revision:
      request.status === "pending" ? 0 : request.status === "approved" ? 1 : 2,
    effectiveness: {
      schema: "qa-approval-effectiveness.v1",
      status:
        request.status === "approved"
          ? "effective"
          : request.status === "revoked"
            ? "revoked"
            : request.status,
      blockers: [],
    },
  };
}

function makeSummaryView(request: RequestReceipt, viewId: string) {
  return {
    schema: "qa-approval-summary-view.v1",
    request_id: request.id,
    view_id: viewId,
    revision: 1,
    subject_hash: request.subject_hash,
    expires_at_ms: Math.min(request.expires_at_ms, Date.now() + 600_000),
    summary: {
      counts: { pass: 2, fail: 0, uncertain: 0, unreviewed: 0 },
      technical_counts: { collected: 2, other: 0 },
      human_pass_rate: { numerator: 2, denominator: 2, value: 1 },
      readiness: "review_complete",
      blockers: [],
      summary_hash: SUMMARY_HASH,
      criteria: { status: "not_defined", approval: "not_approved" },
    },
    view_hash: VIEW_HASH,
  };
}

async function installApprovalRoutes(
  page: Page,
  userId: string,
  options: { unknownFirstDecision?: boolean } = {},
) {
  let current = makeRequest(userId);
  const requests: Array<{ method: string; url: string; body?: unknown }> = [];
  const operationReceipts = new Map<string, RequestReceipt>();
  let postDecisions = 0;

  await page.route("**/api/evaluation/approval-requests**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    const base = `/api/evaluation/approval-requests/${REQUEST_ID}`;
    requests.push({
      method: request.method(),
      url: `${pathname}${url.search}`,
      ...(request.method() === "POST" ? { body: request.postDataJSON() } : {}),
    });

    if (pathname === `${base}/state` && request.method() === "GET") {
      return route.fulfill({ json: makeState(current) });
    }
    if (pathname.startsWith(`${base}/views/`)) {
      const viewId = pathname.split("/").pop()!;
      if (request.method() === "POST") {
        return route.fulfill({ json: makeSummaryView(current, viewId) });
      }
      return route.fulfill({ json: makeSummaryView(current, viewId) });
    }
    if (pathname.startsWith(`${base}/decisions/`)) {
      const operationId = pathname.split("/").pop()!;
      if (request.method() === "GET") {
        const receipt = operationReceipts.get(operationId);
        if (!receipt)
          return route.fulfill({ status: 404, json: { detail: "not found" } });
        return route.fulfill({ json: receipt });
      }

      postDecisions += 1;
      if (options.unknownFirstDecision && postDecisions === 1) {
        const body = request.postDataJSON() as {
          decision: "approved" | "revoked";
        };
        current = {
          ...current,
          status: body.decision,
          revision: current.revision + 1,
          latest_approval_id: operationId,
        };
        operationReceipts.set(operationId, current);
        return route.fulfill({
          status: 503,
          json: { detail: "synthetic unknown write" },
        });
      }

      const body = request.postDataJSON() as {
        decision: "approved" | "revoked";
      };
      current = {
        ...current,
        status: body.decision,
        revision: current.revision + 1,
        latest_approval_id: operationId,
      };
      operationReceipts.set(operationId, current);
      return route.fulfill({ json: current });
    }
    if (
      pathname.startsWith(`${base}/operations/`) &&
      request.method() === "GET"
    ) {
      const operationId = pathname.split("/").pop()!;
      const receipt = operationReceipts.get(operationId);
      if (!receipt)
        return route.fulfill({ status: 404, json: { detail: "not found" } });
      return route.fulfill({ json: receipt });
    }
    if (
      pathname === "/api/evaluation/approval-requests" &&
      request.method() === "GET"
    ) {
      return route.fulfill({
        json: {
          schema: "qa-approval-inbox.v1",
          requests: [current],
          truncated: false,
        },
      });
    }
    if (
      pathname === "/api/evaluation/approval-requests/notifications" &&
      request.method() === "GET"
    ) {
      return route.fulfill({
        json: {
          schema: "qa-approval-notifications.v1",
          notifications: [],
          truncated: false,
        },
      });
    }
    return route.fulfill({
      status: 404,
      json: { detail: "unexpected synthetic route" },
    });
  });

  return {
    requests,
    decisionPostCount: () => postDecisions,
    current: () => current,
  };
}

async function openSignatureCenter(page: Page) {
  await page.goto("/workspace/reviews");
  const center = page.getByRole("region", {
    name: "My signatures and in-app notifications",
  });
  await expect(center).toBeVisible();
  await expect(center.getByLabel("Signature request ID")).toHaveValue("");
  return center;
}

async function registerSecondOrdinaryUser() {
  const client = await request.newContext();
  const email = `approval-assignee-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  const registered = await client.post(`${APP}/api/v1/auth/register`, {
    data: { email, password: PASSWORD },
  });
  expect(registered.status(), await registered.text()).toBe(201);
  const user = (await registered.json()) as {
    id: string;
    system_role: string;
  };
  expect(user.system_role).toBe("user");
  await client.dispose();
  return user;
}

test.describe("authenticated ordinary-user approval signatures", () => {
  test("an ordinary project owner explicitly assigns a fixed run to another ordinary user", async ({
    context,
    page,
  }) => {
    await registerOrdinaryUser(context);
    const assignee = await registerSecondOrdinaryUser();
    const writes: { url: string; body: Record<string, unknown> }[] = [];
    await page.route("**/api/evaluation/projects**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (
        url.pathname === "/api/evaluation/projects" &&
        request.method() === "GET"
      )
        return route.fulfill({
          json: {
            projects: [{ id: "synthetic-project", name: "Synthetic project" }],
          },
        });
      if (
        url.pathname ===
          "/api/evaluation/projects/synthetic-project/datasets" &&
        request.method() === "GET"
      )
        return route.fulfill({ json: { datasets: [] } });
      if (
        url.pathname ===
          "/api/evaluation/projects/synthetic-project/components" &&
        request.method() === "GET"
      )
        return route.fulfill({ json: { components: [] } });
      if (
        url.pathname.startsWith(
          `/api/evaluation/projects/synthetic-project/review-runs/${RUN_ID}/approval-requests/`,
        ) &&
        request.method() === "POST"
      ) {
        const body = request.postDataJSON() as Record<string, unknown>;
        writes.push({ url: url.pathname, body });
        const requestId = url.pathname.split("/").pop()!;
        return route.fulfill({
          json: {
            ...makeRequest(assignee.id),
            id: requestId,
            project_id: "synthetic-project",
            run_id: RUN_ID,
            assessment_id: ASSESSMENT_ID,
            assessment_hash: ASSESSMENT_HASH,
            expires_at_ms: body.expires_at_ms,
          },
        });
      }
      return route.fulfill({
        status: 404,
        json: { detail: "unexpected route" },
      });
    });

    await page.goto("/workspace/datasets");
    await page
      .getByRole("combobox", { name: "Select project", exact: true })
      .selectOption("synthetic-project");
    const approvals = page.getByRole("region", { name: "Formal approvals" });
    const assignment = page.getByRole("region", {
      name: "Assign an authenticated signature",
    });
    await approvals.getByLabel("Run ID").fill(RUN_ID);
    await approvals.getByLabel("Assessment ID").fill(ASSESSMENT_ID);
    await approvals.getByLabel("Assessment hash").fill(ASSESSMENT_HASH);
    await approvals.getByLabel("Approver account").fill(assignee.id);
    const assign = assignment.getByRole("button", {
      name: "Assign signature request",
    });
    await expect(assign).toBeDisabled();
    await assignment.getByLabel("Share this pinned aggregate summary").check();
    await assignment.getByLabel("Confirm signature assignment").check();
    await expect(assign).toBeEnabled();
    await assign.click();
    await expect(assignment.getByRole("status")).toContainText(
      "Signature request created",
    );
    expect(writes).toHaveLength(1);
    expect(writes[0]?.url).toMatch(
      new RegExp(`/review-runs/${RUN_ID}/approval-requests/[0-9a-f]{32}$`),
    );
    expect(writes[0]?.body).toEqual(
      expect.objectContaining({
        assessment_id: ASSESSMENT_ID,
        assessment_hash: ASSESSMENT_HASH,
        approver_id: assignee.id,
        share_summary: true,
        confirmed: true,
      }),
    );
    await expect(page.locator("body")).not.toContainText(
      "SYNTHETIC_CASE_ANSWER",
    );
  });

  test("loads explicitly, opens the pinned summary on demand, then signs and revokes", async ({
    context,
    page,
  }) => {
    const user = await registerOrdinaryUser(context);
    const fixture = await installApprovalRoutes(page, user.id);
    const center = await openSignatureCenter(page);

    expect(fixture.requests).toEqual([]);
    await expect(page.locator("body")).not.toContainText("SYNTHETIC_GOLD");
    await expect(page.locator("body")).not.toContainText(
      "SYNTHETIC_CASE_ANSWER",
    );

    await center.getByLabel("Signature request ID").fill(REQUEST_ID);
    await center
      .getByRole("button", { name: "Load signature request" })
      .click();
    await expect(center.getByTestId("signature-effectiveness")).toHaveText(
      "pending",
    );
    expect(
      fixture.requests.map(({ method, url }) => `${method} ${url}`),
    ).toEqual([`GET /api/evaluation/approval-requests/${REQUEST_ID}/state`]);
    expect(fixture.requests.some(({ url }) => url.includes("/views/"))).toBe(
      false,
    );

    await center.getByRole("button", { name: "Open assigned summary" }).click();
    await expect(center.getByTestId("signature-all-rate")).toHaveText("2 / 2");
    expect(
      fixture.requests
        .filter(({ url }) => url.includes("/views/"))
        .map(({ method }) => method),
    ).toEqual(["POST"]);

    const signButton = center.getByRole("button", {
      name: "Sign this assessment",
    });
    await expect(signButton).toBeDisabled();
    await center.getByLabel("I confirm my own signature").check();
    await signButton.click();
    await expect(center.getByRole("status")).toContainText("Recorded approved");
    expect(fixture.current().status).toBe("approved");

    await center
      .getByRole("button", { name: "Load signature request" })
      .click();
    await expect(center.getByTestId("signature-effectiveness")).toHaveText(
      "effective",
    );
    await center
      .getByLabel("Revocation reason")
      .fill("Synthetic review correction");
    const revokeButton = center.getByRole("button", {
      name: "Revoke my signature",
    });
    await expect(revokeButton).toBeDisabled();
    await center.getByLabel("I confirm my own signature").check();
    await revokeButton.click();
    await expect(center.getByRole("status")).toContainText("Recorded revoked");
    expect(fixture.current().status).toBe("revoked");

    const decisions = fixture.requests.filter(({ url }) =>
      url.includes("/decisions/"),
    );
    expect(decisions.map(({ method }) => method)).toEqual(["POST", "POST"]);
    expect(decisions[0]?.body).toEqual(
      expect.objectContaining({ decision: "approved", confirmed: true }),
    );
    expect(decisions[1]?.body).toEqual(
      expect.objectContaining({
        decision: "revoked",
        confirmed: true,
        note: "Synthetic review correction",
      }),
    );
    expect(
      fixture.requests.some(({ url }) =>
        /\/(cases|evidence|references|open)\b/.test(url),
      ),
    ).toBe(false);
  });

  test("unknown signature write reconciles only the original operation ID", async ({
    context,
    page,
  }) => {
    const user = await registerOrdinaryUser(context);
    const fixture = await installApprovalRoutes(page, user.id, {
      unknownFirstDecision: true,
    });
    const center = await openSignatureCenter(page);

    await center.getByLabel("Signature request ID").fill(REQUEST_ID);
    await center
      .getByRole("button", { name: "Load signature request" })
      .click();
    await expect(center.getByTestId("signature-effectiveness")).toHaveText(
      "pending",
    );
    await center.getByRole("button", { name: "Open assigned summary" }).click();
    await expect(center.getByTestId("signature-all-rate")).toHaveText("2 / 2");
    await center.getByLabel("I confirm my own signature").check();
    await center.getByRole("button", { name: "Sign this assessment" }).click();

    const reconcile = center.getByRole("button", {
      name: "Reconcile original operation",
    });
    await expect(reconcile).toBeVisible();
    const post = fixture.requests.find(
      ({ method, url }) => method === "POST" && url.includes("/decisions/"),
    );
    expect(post).toBeTruthy();
    const operationId = post!.url.split("/").pop()!;
    expect(operationId).toMatch(/^[0-9a-f]{32}$/);

    await reconcile.click();
    await expect(center.getByRole("status")).toContainText(
      "Original ID reconciled",
    );
    const operationReads = fixture.requests.filter(
      ({ method, url }) =>
        method === "GET" && url.endsWith(`/operations/${operationId}`),
    );
    expect(operationReads).toHaveLength(1);
    expect(fixture.decisionPostCount()).toBe(1);
    expect(
      fixture.requests.filter(
        ({ method, url }) => method === "POST" && url.includes("/decisions/"),
      ),
    ).toHaveLength(1);
    expect(fixture.current().status).toBe("approved");
    expect(
      fixture.requests.some(({ url }) =>
        /\/(cases|evidence|references|open)\b/.test(url),
      ),
    ).toBe(false);
  });
});
