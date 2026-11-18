import { z } from "zod";

const id = z.string().regex(/^[0-9a-f]{32}$/);
const hash = z.string().regex(/^[0-9a-f]{64}$/);
const integer = z.number().int().nonnegative().safe();
const revision = integer.min(1).max(1000);
const count = integer.max(1000);
const decision = z.enum(["approved", "revoked"]);
const blockers = z.array(z.string().min(1).max(128)).max(100);
const assessment = z.object({ id, revision, assessment_hash: hash }).strict();

export const approvalMetadataSchema = z
  .object({
    id,
    project_id: z.string(),
    run_id: z.string(),
    revision,
    created_at_ms: integer,
    assessment_id: id,
    assessment_hash: hash,
    approver_id: z.string().uuid(),
    decision,
    approval_hash: hash,
  })
  .strict();
export const projectApprovalSchema = approvalMetadataSchema.pick({
  id: true,
  run_id: true,
  revision: true,
  created_at_ms: true,
  assessment_id: true,
  assessment_hash: true,
  decision: true,
});
export const auditSchema = z
  .object({
    project_id: z.string(),
    run_id: z.string(),
    sequence: revision,
    approval_id: id,
    revision,
    actor: z.string(),
    action: decision,
    subject_hash: hash,
    at_ms: integer,
  })
  .strict();
export const assessmentSchema = z
  .object({
    id,
    project_id: z.string(),
    run_id: z.string(),
    revision,
    created_at_ms: integer,
    summary_hash: hash,
    assessment_hash: hash,
  })
  .strict();
export const preflightSchema = z
  .object({
    schema: z.literal("qa-approval-preflight.v1"),
    scope: z.literal("read_only_formal_approval_preflight"),
    project_id: z.string(),
    run_id: z.string(),
    assessment,
    approver_id: z.string().uuid(),
    eligible: z.boolean(),
    blockers,
    readiness: z.string(),
    criteria: z.object({ status: z.string() }).strict(),
    separation: z
      .object({
        approver_not_owner: z.boolean(),
        approver_not_review_actor: z.boolean(),
      })
      .strict(),
    latest_approval: z.object({ revision, decision }).strict().nullable(),
    approval: z.literal("not_recorded"),
  })
  .strict()
  .refine(
    (value) =>
      value.eligible === (value.blockers.length === 0) &&
      (!value.eligible ||
        (value.separation.approver_not_owner &&
          value.separation.approver_not_review_actor &&
          value.readiness === "review_complete" &&
          ["met", "not_defined"].includes(value.criteria.status))),
  );
export const chainSchema = z
  .object({
    schema: z.literal("qa-approval-chain.v1"),
    scope: z.literal("approval_audit_chain_only"),
    status: z.enum(["verified", "broken"]),
    approvals: integer.max(1001),
    events: integer.max(1001),
    blockers,
  })
  .strict()
  .refine((value) =>
    value.status === "verified"
      ? value.blockers.length === 0 && value.approvals === value.events
      : value.blockers.length > 0,
  );
export const chainSummarySchema = z
  .object({
    schema: z.literal("qa-approval-chain-summary.v1"),
    scope: z.literal("project_approval_audit_chains_only"),
    status: z.enum(["verified", "broken", "unverifiable"]),
    runs: integer,
    verified_runs: integer,
    broken_runs: integer,
    approvals: integer,
    events: integer,
    blockers,
  })
  .strict()
  .refine((value) =>
    value.status === "unverifiable"
      ? value.blockers.length > 0 &&
        value.verified_runs === 0 &&
        value.broken_runs === 0
      : value.runs === value.verified_runs + value.broken_runs &&
        (value.status === "verified"
          ? value.blockers.length === 0 &&
            value.broken_runs === 0 &&
            value.approvals === value.events
          : value.blockers.length > 0 && value.broken_runs > 0),
  );
const policySchema = z
  .object({
    schema: z.literal("qa-approval-signoff-policy.v1"),
    scope: z.literal("advisory_signoff_policy_only"),
    project_id: z.string(),
    revision,
    required_distinct_approvers: integer.min(1).max(10),
    created_at_ms: integer,
    advisory: z.literal(true),
    enforcement: z.literal("none"),
    policy_hash: hash,
  })
  .strict();
const requirementSchema = z
  .object({
    schema: z.literal("qa-signoff-requirement.v1"),
    scope: z.literal("technical_signoff_requirement_only"),
    policy: z
      .object({
        defined: z.boolean(),
        required_distinct_approvers: integer.min(1).max(10).nullable(),
      })
      .strict(),
    observed: z
      .object({
        distinct_approved_approvers: count,
        latest_decision: decision.nullable(),
      })
      .strict(),
    satisfied: z.boolean().nullable(),
    blockers,
    approval: z.literal("not_approved"),
    source: z.enum(["stored_advisory", "request_only"]).optional(),
  })
  .strict();
export const signoffSchema = z
  .object({
    schema: z.literal("qa-approval-signoff.v1"),
    scope: z.literal("approval_signoff_progress_only"),
    policy: z.literal("not_defined"),
    required_distinct_approvers: z.null(),
    revisions: count,
    distinct_approvers: count,
    distinct_approved_approvers: count,
    approved_revisions: count,
    revoked_revisions: count,
    latest_revision: revision.nullable(),
    latest_decision: decision.nullable(),
    multi_level_satisfied: z.null(),
    blockers,
    requirement: requirementSchema.optional(),
    stored_policy: policySchema.optional(),
  })
  .strict()
  .refine(
    (value) =>
      value.revisions === value.approved_revisions + value.revoked_revisions &&
      value.distinct_approvers <= value.revisions &&
      value.distinct_approved_approvers <= value.approved_revisions &&
      value.distinct_approved_approvers <= value.distinct_approvers &&
      (value.revisions === 0
        ? value.latest_revision === null && value.latest_decision === null
        : value.latest_revision === value.revisions &&
          value.latest_decision !== null) &&
      (!value.requirement ||
        (value.requirement.observed.distinct_approved_approvers ===
          value.distinct_approved_approvers &&
          value.requirement.observed.latest_decision ===
            value.latest_decision)),
  );
export const capabilitiesSchema = z
  .object({
    schema: z.literal("qa-approval-capabilities.v1"),
    scope: z.literal("approval_capability_diagnostic_only"),
    approver_login: z.literal("assigned_request_only"),
    owner_records_on_behalf: z.literal(true),
    multi_level_policy: z.literal("advisory_only"),
    multi_level_enforcement: z.literal("not_implemented"),
    notifications: z.literal("in_app_only"),
    export: z.literal("not_implemented"),
    approval: z.literal("not_authorized"),
    blockers,
  })
  .strict();
export const approvalViewSchema = z
  .object({
    schema: z.literal("qa-run-formal-approval.v1"),
    scope: z.literal("formal_approval_decision"),
    id,
    project_id: z.string(),
    run_id: z.string(),
    revision,
    created_at_ms: integer,
    recorded_by: z.string(),
    policy: z
      .object({
        id: z.literal("independent-double-blind.v1"),
        population: z.literal("all_frozen_effectiveness_samples"),
        source: z.literal("immutable_independent_assessment"),
        separation: z.literal("approver_not_owner_or_independent_reviewer"),
      })
      .strict(),
    assessment: assessment.extend({ summary_hash: hash }),
    counts: z.record(z.string(), integer),
    technical_counts: z.record(z.string(), integer),
    human_pass_rate: z.object({
      numerator: integer,
      denominator: integer,
      value: z.number().min(0).max(1).nullable(),
    }),
    criteria: z.object({
      status: z.string(),
      approval: z.literal("not_approved"),
    }),
    readiness: z.literal("review_complete"),
    decision,
    approver_id: z.string().uuid(),
    note: z.string().max(2000).nullable(),
    approval_hash: hash,
  })
  .strict();

export type ApprovalDecision = z.infer<typeof decision>;
export type ProjectApproval = z.infer<typeof projectApprovalSchema>;
export type ApprovalMetadata = z.infer<typeof approvalMetadataSchema>;
export type ApprovalAuditEvent = z.infer<typeof auditSchema>;
export type ApprovalPreflight = z.infer<typeof preflightSchema>;
export type ApprovalChainIntegrity = z.infer<typeof chainSchema>;
export type ApprovalChainSummary = z.infer<typeof chainSummarySchema>;
export type ApprovalSignoffPolicy = z.infer<typeof policySchema>;
export type ApprovalSignoffRequirement = z.infer<typeof requirementSchema>;
export type ApprovalSignoffProgress = z.infer<typeof signoffSchema>;
export type ApprovalCapabilities = z.infer<typeof capabilitiesSchema>;
export type RunAssessment = z.infer<typeof assessmentSchema>;
export type ApprovalView = z.infer<typeof approvalViewSchema>;
