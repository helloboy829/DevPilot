import { beforeEach, expect, test, rs } from "@rstest/core";

const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));

import { signatureApi } from "@/core/evaluation/approval-requests";

const requestId = "d".repeat(32);
const viewId = "e".repeat(32);
const operationId = "f".repeat(32);
const actor = "00000000-0000-0000-0000-000000000005";
const receipt = {
  schema: "qa-approval-request.v1",
  id: requestId,
  project_id: "project 1",
  run_id: "a".repeat(32),
  assessment_id: "c".repeat(32),
  assessment_hash: "1".repeat(64),
  approver_id: actor,
  created_at_ms: 1000,
  expires_at_ms: 61000,
  subject_hash: "2".repeat(64),
  revision: 1,
  status: "pending",
  latest_approval_id: null,
} as const;
const command = {
  expected_revision: 1,
  subject_hash: receipt.subject_hash,
  confirmed: true as const,
};

beforeEach(() => state.api.mockReset());

test("inbox is bounded and tied to the currently signed-in assignee", async () => {
  state.api.mockResolvedValue({
    schema: "qa-approval-inbox.v1",
    requests: [receipt],
    truncated: false,
  });
  expect((await signatureApi.inbox(actor)).requests).toEqual([receipt]);
  expect(state.api).toHaveBeenCalledWith(
    "evaluation/approval-requests",
    undefined,
    "POST",
    262144,
  );
  await expect(signatureApi.inbox("other-account")).rejects.toThrow();
  state.api.mockResolvedValue({
    schema: "qa-approval-inbox.v1",
    requests: Array.from({ length: 101 }, () => receipt),
    truncated: false,
  });
  await expect(signatureApi.inbox(actor)).rejects.toThrow();
});

test("original operation GET validates request identity and never writes", async () => {
  const signed = {
    ...receipt,
    status: "approved",
    revision: 2,
    latest_approval_id: operationId,
  };
  state.api.mockResolvedValue(signed);
  expect(await signatureApi.operation(requestId, operationId)).toEqual(signed);
  expect(state.api).toHaveBeenCalledWith(
    `evaluation/approval-requests/${requestId}/operations/${operationId}`,
    undefined,
    "POST",
    262144,
  );
  state.api.mockResolvedValue({ ...signed, id: "9".repeat(32) });
  await expect(
    signatureApi.operation(requestId, operationId),
  ).rejects.toThrow();
});

test("summary receipt rejects case data and inconsistent ALL counts", async () => {
  const opened = {
    schema: "qa-approval-summary-view.v1",
    request_id: requestId,
    view_id: viewId,
    revision: 1,
    subject_hash: receipt.subject_hash,
    expires_at_ms: 61000,
    view_hash: "3".repeat(64),
    summary: {
      counts: { pass: 2, fail: 0, uncertain: 0, unreviewed: 0 },
      technical_counts: { collected: 2, other: 0 },
      human_pass_rate: { numerator: 2, denominator: 2, value: 1 },
      readiness: "review_complete",
      blockers: [],
      summary_hash: "4".repeat(64),
      criteria: { status: "not_defined", approval: "not_approved" },
    },
  };
  state.api.mockResolvedValue(opened);
  expect(await signatureApi.open(receipt, viewId)).toEqual(opened);
  expect(state.api).toHaveBeenCalledWith(
    `evaluation/approval-requests/${requestId}/views/${viewId}`,
    command,
    "POST",
    262144,
  );
  state.api.mockResolvedValue({
    ...opened,
    summary: { ...opened.summary, cases: ["SYNTHETIC_SECRET"] },
  });
  await expect(signatureApi.view(receipt, viewId)).rejects.toThrow();
  state.api.mockResolvedValue({
    ...opened,
    summary: {
      ...opened.summary,
      human_pass_rate: { numerator: 2, denominator: 3, value: 1 },
    },
  });
  await expect(signatureApi.view(receipt, viewId)).rejects.toThrow();
});

test("decision sends no client actor and validates the resulting transition", async () => {
  const signed = {
    ...receipt,
    status: "approved",
    revision: 2,
    latest_approval_id: operationId,
  };
  state.api.mockResolvedValue(signed);
  await signatureApi.decide(receipt, operationId, "approved", 0, viewId);
  expect(state.api).toHaveBeenCalledWith(
    `evaluation/approval-requests/${requestId}/decisions/${operationId}`,
    {
      ...command,
      decision: "approved",
      expected_previous_approval_revision: 0,
      view_id: viewId,
    },
    "POST",
    262144,
  );
  state.api.mockResolvedValue(receipt);
  await expect(
    signatureApi.decide(receipt, operationId, "approved", 0, viewId),
  ).rejects.toThrow();
});

test("metadata and state reject forged lifecycle combinations", async () => {
  for (const damage of [
    { status: "approved" },
    { revision: 2 },
    { expires_at_ms: 1000 },
    { document: "SYNTHETIC_SECRET" },
  ]) {
    state.api.mockResolvedValue({ ...receipt, ...damage });
    await expect(signatureApi.get(requestId)).rejects.toThrow();
  }
});

test("notifications accept only bounded fixed events without evidence", async () => {
  state.api.mockResolvedValue({
    schema: "qa-approval-notifications.v1",
    notifications: [
      {
        request_id: requestId,
        operation_id: requestId,
        action: "requested",
        at_ms: 1000,
        revision: 1,
      },
    ],
    truncated: false,
  });
  expect((await signatureApi.notifications()).notifications).toHaveLength(1);
  state.api.mockResolvedValue({
    schema: "qa-approval-notifications.v1",
    notifications: [
      {
        request_id: requestId,
        operation_id: requestId,
        action: "requested",
        at_ms: 1000,
        revision: 1,
        note: "SYNTHETIC_SECRET",
      },
    ],
    truncated: false,
  });
  await expect(signatureApi.notifications()).rejects.toThrow();
});

test("accepts the real frozen criteria projection and rejects a forged met threshold", async () => {
  const opened = {
    schema: "qa-approval-summary-view.v1",
    request_id: requestId,
    view_id: viewId,
    revision: 1,
    subject_hash: receipt.subject_hash,
    expires_at_ms: 61000,
    view_hash: "3".repeat(64),
    summary: {
      counts: { pass: 2, fail: 0, uncertain: 0, unreviewed: 0 },
      technical_counts: { collected: 2, other: 0 },
      human_pass_rate: { numerator: 2, denominator: 2, value: 1 },
      readiness: "review_complete",
      blockers: [],
      summary_hash: "4".repeat(64),
      criteria: {
        scope: "effectiveness_threshold_only",
        criteria: {
          schema: "qa-effectiveness-criteria.v1",
          version_label: "frozen-1",
          min_pass_rate_bps: 5000,
        },
        status: "met",
        blockers: [],
        approval: "not_approved",
      },
    },
  };
  state.api.mockResolvedValue(opened);
  expect(await signatureApi.view(receipt, viewId)).toEqual(opened);
  state.api.mockResolvedValue({
    ...opened,
    summary: {
      ...opened.summary,
      counts: { ...opened.summary.counts, pass: 0, fail: 2 },
      human_pass_rate: { numerator: 0, denominator: 2, value: 0 },
    },
  });
  await expect(signatureApi.view(receipt, viewId)).rejects.toThrow();
});
