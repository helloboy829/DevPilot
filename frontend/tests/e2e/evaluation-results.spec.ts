import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const width of [1440, 390]) {
  test(`effectiveness results require explicit reads and clear response (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    mockLangGraphAPI(page, { threads: [] });
    let runReads = 0;
    let caseReads = 0;
    let grantReads = 0;
    let evidenceReads = 0;
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
    await page.route("**/api/evaluation/projects/p1/runs**", (route) => {
      runReads++;
      return route.fulfill({
        json: {
          items: [
            {
              run_id: "r1",
              project_id: "p1",
              plan_id: "pl1",
              component_id: "c1",
              dataset_id: "d1",
              status: "finished",
              started_at_ms: 1800000000000,
              finished_at_ms: 1800000001000,
              total: 1,
              request_count: 1,
              concurrency: 1,
              verdict: "NOT_EVALUATED",
              blockers: [],
              technical_counts: { succeeded: 1 },
            },
          ],
          total: 1,
          matched_total: 1,
          next_cursor: null,
        },
      });
    });
    await page.route("**/api/evaluation/projects/p1/runs/r1", (route) =>
      route.fulfill({
        json: {
          run_id: "r1",
          project_id: "p1",
          plan_id: "pl1",
          component_id: "c1",
          dataset_id: "d1",
          status: "finished",
          started_at_ms: 1800000000000,
          finished_at_ms: 1800000001000,
          total: 1,
          request_count: 1,
          concurrency: 1,
          verdict: "NOT_EVALUATED",
          blockers: [],
          technical_counts: { succeeded: 1 },
        },
      }),
    );
    await page.route(
      "**/api/evaluation/projects/p1/runs/r1/cases?**",
      (route) => {
        caseReads++;
        return route.fulfill({
          json: {
            items: [
              {
                case_id: "case-1",
                ordinal: 1,
                integrity_status: "complete",
                reference_status: "provided",
                dispatch_state: "succeeded",
                kind: "http",
                http_status: 200,
                latency_ms: 12,
                response_bytes: 20,
                output_evidence: { available: true },
                response_evidence: {
                  status: "complete",
                  hash_scope: "full",
                  sha256:
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                  captured_bytes: 20,
                  observed_bytes: 20,
                  content_type: "text/html",
                },
              },
            ],
            total: 1,
            matched_total: 1,
            next_cursor: null,
          },
        });
      },
    );
    await page.route(
      "**/api/evaluation/projects/p1/runs/r1/cases/case-1",
      (route) =>
        route.fulfill({
          json: {
            case_id: "case-1",
            ordinal: 1,
            integrity_status: "complete",
            reference_status: "provided",
            dispatch_state: "succeeded",
            kind: "http",
            http_status: 200,
            latency_ms: 12,
            response_bytes: 20,
            output_evidence: { available: true },
            response_evidence: {
              status: "complete",
              hash_scope: "full",
              sha256:
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
              captured_bytes: 20,
              observed_bytes: 20,
              content_type: "text/html",
            },
          },
        }),
    );
    await page.route("**/review-runs/r1/cases/1/evidence-access", (route) => {
      grantReads++;
      expect(route.request().postDataJSON()).toEqual({
        kind: "response",
        evidence_hash: "a".repeat(64),
        confirmed: true,
      });
      return route.fulfill({
        json: {
          access_id: "opaque",
          evidence_kind: "response",
          expires_at_ms: 1800000300000,
        },
      });
    });
    await page.route(
      "**/api/evaluation/projects/p1/evidence/opaque",
      (route) => {
        evidenceReads++;
        return route.fulfill({
          status: 200,
          contentType: "application/octet-stream",
          body: "<script>synthetic response</script>",
        });
      },
    );

    await page.goto("/workspace/effectiveness-results");
    expect(runReads).toBe(0);
    expect(caseReads).toBe(0);
    await page.getByRole("button", { name: "Load projects" }).click();
    await page.getByRole("combobox", { name: "Project" }).selectOption("p1");
    await page.getByRole("button", { name: "Load runs" }).click();
    await expect(page.getByRole("button", { name: /r1/ })).toBeVisible();
    await page.getByRole("button", { name: /r1/ }).click();
    await page.getByRole("button", { name: "Load cases" }).click();
    await page.getByRole("button", { name: "Details" }).click();
    await page
      .getByRole("button", { name: "Authorize and view captured response" })
      .click();
    await expect(
      page.getByText("<script>synthetic response</script>"),
    ).toBeVisible();
    expect(grantReads).toBe(1);
    expect(evidenceReads).toBe(1);
    await page.getByRole("combobox", { name: "Project" }).selectOption("p2");
    await expect(
      page.getByText("<script>synthetic response</script>"),
    ).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}
