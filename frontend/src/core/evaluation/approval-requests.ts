import { z } from "zod";

import { evaluationApi } from "./api";

const id = z.string().regex(/^[0-9a-f]{32}$/);
const hash = z.string().regex(/^[0-9a-f]{64}$/);
const integer = z.number().int().nonnegative().safe();
const time = integer.positive().max(253402300799000);
const revision = integer.min(1).max(3);

export const signatureRequestSchema = z
  .object({
    schema: z.literal("qa-approval-request.v1"),
    id,
    project_id: z.string().min(1).max(64),
    run_id: id,
    assessment_id: id,
    assessment_hash: hash,
    approver_id: z.string().uuid(),
    created_at_ms: time,
    expires_at_ms: time,
    subject_hash: hash,
    revision,
    status: z.enum(["pending", "approved", "revoked", "cancelled"]),
    latest_approval_id: id.nullable(),
  })
  .strict()
  .refine(
    (value) =>
      value.expires_at_ms > value.created_at_ms &&
      ((value.status === "pending" &&
        value.revision === 1 &&
        value.latest_approval_id === null) ||
        (value.status === "cancelled" &&
          value.revision === 2 &&
          value.latest_approval_id === null) ||
        (value.status === "approved" &&
          value.revision === 2 &&
          value.latest_approval_id !== null) ||
        (value.status === "revoked" &&
          value.revision === 3 &&
          value.latest_approval_id !== null)),
  );
export type SignatureRequest = z.infer<typeof signatureRequestSchema>;

const effectivenessSchema = z
  .object({
    schema: z.literal("qa-approval-effectiveness.v1"),
    status: z.enum([
      "pending",
      "effective",
      "expired",
      "stale",
      "revoked",
      "cancelled",
      "unverifiable",
      "superseded",
    ]),
    blockers: z
      .array(
        z.enum([
          "approval_chain_broken",
          "request_expired",
          "assessment_source_changed",
          "source_changed_during_observation",
          "newer_signature_decision",
        ]),
      )
      .max(5),
  })
  .strict();
const summarySchema = z
  .object({
    counts: z
      .object({
        pass: integer,
        fail: integer,
        uncertain: z.literal(0),
        unreviewed: z.literal(0),
      })
      .strict(),
    technical_counts: z
      .object({ collected: integer, other: z.literal(0) })
      .strict(),
    human_pass_rate: z
      .object({
        numerator: integer,
        denominator: integer.positive(),
        value: z.number().min(0).max(1),
      })
      .strict(),
    readiness: z.literal("review_complete"),
    blockers: z.array(z.never()).max(0),
    summary_hash: hash,
    criteria: z.discriminatedUnion("status", [
      z
        .object({
          status: z.literal("not_defined"),
          approval: z.literal("not_approved"),
        })
        .strict(),
      z
        .object({
          status: z.literal("met"),
          approval: z.literal("not_approved"),
          scope: z.literal("effectiveness_threshold_only"),
          blockers: z.array(z.never()).max(0),
          criteria: z
            .object({
              schema: z.literal("qa-effectiveness-criteria.v1"),
              version_label: z.string().min(1).max(80),
              min_pass_rate_bps: integer.max(10000),
            })
            .strict(),
        })
        .strict(),
    ]),
  })
  .strict()
  .refine((value) => {
    const all = value.human_pass_rate.denominator;
    return (
      value.counts.pass + value.counts.fail === all &&
      value.technical_counts.collected === all &&
      value.human_pass_rate.numerator === value.counts.pass &&
      value.human_pass_rate.value === value.counts.pass / all &&
      (value.criteria.status === "not_defined" ||
        value.counts.pass * 10000 >=
          all * value.criteria.criteria.min_pass_rate_bps)
    );
  });
const viewSchema = z
  .object({
    schema: z.literal("qa-approval-summary-view.v1"),
    request_id: id,
    view_id: id,
    revision: z.literal(1),
    subject_hash: hash,
    expires_at_ms: time,
    summary: summarySchema,
    view_hash: hash,
  })
  .strict();
export type SignatureSummaryView = z.infer<typeof viewSchema>;
const stateSchema = z
  .object({
    schema: z.literal("qa-approval-request-state.v1"),
    request: signatureRequestSchema,
    approval_revision: integer.max(1000),
    effectiveness: effectivenessSchema,
  })
  .strict();
export type SignatureState = z.infer<typeof stateSchema>;
const inboxSchema = z
  .object({
    schema: z.literal("qa-approval-inbox.v1"),
    requests: z.array(signatureRequestSchema).max(100),
    truncated: z.boolean(),
  })
  .strict();
const noticesSchema = z
  .object({
    schema: z.literal("qa-approval-notifications.v1"),
    truncated: z.boolean(),
    notifications: z
      .array(
        z
          .object({
            request_id: id,
            operation_id: id,
            action: z.enum(["requested", "approved", "revoked", "cancelled"]),
            at_ms: time,
            revision,
          })
          .strict(),
      )
      .max(100),
  })
  .strict();
export type SignatureNotices = z.infer<typeof noticesSchema>;

const root = "evaluation/approval-requests";
const path = (requestId: string) => `${root}/${id.parse(requestId)}`;
const invalid = () => new Error("Invalid signature response");
async function request<S extends z.ZodType>(
  route: string,
  schema: S,
  body?: unknown,
): Promise<z.output<S>> {
  const result = schema.safeParse(
    await evaluationApi<unknown>(route, body, "POST", 262144),
  );
  if (!result.success) throw invalid();
  return result.data;
}
function scoped(value: SignatureRequest, requestId: string) {
  if (value.id !== requestId) throw invalid();
  return value;
}
function pinned(value: SignatureRequest, source: SignatureRequest) {
  if (
    value.id !== source.id ||
    value.subject_hash !== source.subject_hash ||
    value.assessment_hash !== source.assessment_hash ||
    value.approver_id !== source.approver_id ||
    value.project_id !== source.project_id ||
    value.run_id !== source.run_id ||
    value.assessment_id !== source.assessment_id
  )
    throw invalid();
  return value;
}
const command = (source: SignatureRequest) => ({
  expected_revision: source.revision,
  subject_hash: source.subject_hash,
  confirmed: true as const,
});
function viewMatches(
  value: SignatureSummaryView,
  source: SignatureRequest,
  viewId: string,
) {
  if (
    value.request_id !== source.id ||
    value.view_id !== viewId ||
    value.subject_hash !== source.subject_hash ||
    value.expires_at_ms > source.expires_at_ms
  )
    throw invalid();
  return value;
}

export const signatureApi = {
  async inbox(actor: string) {
    const result = await request(root, inboxSchema);
    if (
      result.requests.some((row) => row.approver_id !== actor) ||
      new Set(result.requests.map((row) => row.id)).size !==
        result.requests.length
    )
      throw invalid();
    return result;
  },
  notifications() {
    return request(`${root}/notifications`, noticesSchema);
  },
  async get(requestId: string) {
    return scoped(
      await request(path(requestId), signatureRequestSchema),
      requestId,
    );
  },
  async state(requestId: string) {
    const value = await request(`${path(requestId)}/state`, stateSchema);
    scoped(value.request, requestId);
    return value;
  },
  async operation(requestId: string, operationId: string) {
    return scoped(
      await request(
        `${path(requestId)}/operations/${id.parse(operationId)}`,
        signatureRequestSchema,
      ),
      requestId,
    );
  },
  async open(source: SignatureRequest, viewId: string) {
    return viewMatches(
      await request(
        `${path(source.id)}/views/${id.parse(viewId)}`,
        viewSchema,
        command(source),
      ),
      source,
      viewId,
    );
  },
  async view(source: SignatureRequest, viewId: string) {
    return viewMatches(
      await request(`${path(source.id)}/views/${id.parse(viewId)}`, viewSchema),
      source,
      viewId,
    );
  },
  async decide(
    source: SignatureRequest,
    operationId: string,
    decision: "approved" | "revoked",
    previous: number,
    viewId?: string,
    note?: string,
  ) {
    const value = pinned(
      await request(
        `${path(source.id)}/decisions/${id.parse(operationId)}`,
        signatureRequestSchema,
        {
          ...command(source),
          decision,
          expected_previous_approval_revision: previous,
          ...(viewId ? { view_id: id.parse(viewId) } : {}),
          ...(note ? { note } : {}),
        },
      ),
      source,
    );
    if (
      value.status !== decision ||
      value.latest_approval_id !== operationId ||
      value.revision !== source.revision + 1
    )
      throw invalid();
    return value;
  },
  async cancel(source: SignatureRequest, operationId: string) {
    const value = pinned(
      await request(
        `${path(source.id)}/cancellations/${id.parse(operationId)}`,
        signatureRequestSchema,
        command(source),
      ),
      source,
    );
    if (value.status !== "cancelled" || value.revision !== source.revision + 1)
      throw invalid();
    return value;
  },
  async create(
    projectId: string,
    runId: string,
    requestId: string,
    payload: {
      assessment_id: string;
      assessment_hash: string;
      approver_id: string;
      expires_at_ms: number;
      share_summary: true;
      confirmed: true;
    },
  ) {
    const result = scoped(
      await request(
        `evaluation/projects/${encodeURIComponent(projectId)}/review-runs/${id.parse(runId)}/approval-requests/${id.parse(requestId)}`,
        signatureRequestSchema,
        payload,
      ),
      requestId,
    );
    if (
      result.project_id !== projectId ||
      result.run_id !== runId ||
      result.assessment_id !== payload.assessment_id ||
      result.assessment_hash !== payload.assessment_hash ||
      result.approver_id !== payload.approver_id ||
      result.expires_at_ms !== payload.expires_at_ms ||
      result.status !== "pending"
    )
      throw invalid();
    return result;
  },
};
