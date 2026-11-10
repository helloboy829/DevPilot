import { z } from "zod";

const identifier = z.string().regex(/^[A-Za-z0-9_-]{1,64}$/);
const id = z.string().regex(/^[0-9a-f]{32}$/);
const hash = z.string().regex(/^[0-9a-f]{64}$/);
const time = z.number().int().min(1).max(253_402_300_799_000);
const account = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
const tier = z.enum(["skeleton", "baseline_inputs"]);
const origin = z
  .string()
  .max(2048)
  .refine((value) => {
    try {
      const url = new URL(value);
      const port = url.port || (url.protocol === "https:" ? "443" : "80");
      return (
        ["http:", "https:"].includes(url.protocol) &&
        !url.username &&
        !url.password &&
        !url.search &&
        !url.hash &&
        url.pathname === "/" &&
        value === `${url.protocol}//${url.hostname}:${port}`
      );
    } catch {
      return false;
    }
  });
const grantSchema = z
  .object({
    id,
    owner_id: identifier,
    project_id: identifier,
    plan_id: identifier,
    plan_hash: hash,
    recipient_id: account,
    tier,
    target_origin: origin,
    off_platform_authorized: z.literal(true),
    expires_at_ms: time,
  })
  .strict();
export type ExportGrant = z.infer<typeof grantSchema>;
const capabilitySchema = z
  .object({
    schema: z.literal("platform-qa-export-capabilities.v1"),
    project_id: identifier,
    checked_at_ms: time,
    enabled: z.boolean(),
    software_archive_sha256: hash.nullable(),
    max_response_bytes: z.number().int().min(1).max(1_048_576),
    max_total_response_bytes: z.number().int().min(2).max(67_108_864),
    grants: z.array(grantSchema).max(200),
    execution_authorized: z.literal(false),
    approval: z.literal(false),
    verdict: z.literal("NOT_EVALUATED"),
  })
  .strict();
export type ExportCapabilities = z.infer<typeof capabilitySchema>;
export function parseExportCapabilities(
  raw: unknown,
  projectId: string,
): ExportCapabilities {
  const doc = capabilitySchema.parse(raw);
  if (
    doc.project_id !== projectId ||
    (!doc.enabled &&
      (doc.grants.length > 0 || doc.software_archive_sha256 !== null)) ||
    (doc.enabled && doc.software_archive_sha256 === null) ||
    new Set(doc.grants.map((g) => g.id)).size !== doc.grants.length ||
    doc.grants.some(
      (g) => g.project_id !== projectId || g.expires_at_ms <= doc.checked_at_ms,
    )
  )
    throw new Error("Invalid export policy metadata");
  return doc;
}
const planSchema = z.object({
  id: identifier,
  project_id: identifier,
  definition_hash: hash,
  version_label: z.string().min(1).max(160),
  scope: z.literal("frozen_definition_only"),
  definition: z.object({
    schema: z.enum(["qa-json-plan.v1", "qa-json-plan.v2"]),
    scope: z.literal("frozen_definition_only"),
    project_id: identifier,
    dataset_purpose: z.enum(["baseline", "acceptance"]),
    limits: z.object({ mode: z.literal("effectiveness") }),
    preflight: z.object({ sample_count: z.number().int().min(1).max(500) }),
  }),
});
export function parseExportPlan(raw: unknown, grant: ExportGrant) {
  const plan = planSchema.parse(raw);
  if (
    plan.id !== grant.plan_id ||
    plan.project_id !== grant.project_id ||
    plan.definition.project_id !== grant.project_id ||
    plan.definition_hash !== grant.plan_hash ||
    (grant.tier === "baseline_inputs" &&
      plan.definition.dataset_purpose !== "baseline")
  )
    throw new Error("Frozen source does not match the selected grant");
  return {
    id: plan.id,
    hash: plan.definition_hash,
    label: plan.version_label,
    sampleCount: plan.definition.preflight.sample_count,
    schema: plan.definition.schema,
  };
}
export type ExportPlan = ReturnType<typeof parseExportPlan>;
export interface ExportCreate {
  plan_id: string;
  plan_hash: string;
  grant_id: string;
  recipient_id: string;
  tier: ExportGrant["tier"];
  confirmed: true;
  data_use_confirmed: true;
  external_controls_acknowledged: true;
}
export interface PendingExport {
  id: string;
  projectId: string;
  request: ExportCreate;
  grant: ExportGrant;
  sampleCount: number;
  planSchema: ExportPlan["schema"];
  softwareHash: string;
}
export type PendingExports = Map<string, PendingExport>;
export const exportIdValid = (value: string) => id.safeParse(value).success;
const receiptSchema = z
  .object({
    schema: z.literal("platform-qa-export-receipt.v1"),
    scope: z.literal("authorized_external_configuration_only"),
    exporter: z.literal("platform-local-qa-config.v1"),
    id,
    project_id: identifier,
    plan_id: identifier,
    plan_hash: hash,
    grant: grantSchema,
    policy_hash: hash,
    recipient_id: account,
    tier,
    dataset_id: identifier,
    dataset_revision: z.number().int().min(1),
    dataset_hash: hash,
    request_version_id: identifier,
    request_protected_hash: hash,
    source_plan_schema: z.enum(["qa-json-plan.v1", "qa-json-plan.v2"]),
    all_frozen_samples: z.number().int().min(1).max(500),
    manifest_fingerprint: hash,
    software_archive_sha256: hash,
    sealed_bundle_hash: hash,
    bundle_bytes: z.number().int().min(1).max(5_242_880),
    created_at_ms: time,
    input_set_complete: z.boolean(),
    ready_for_preflight: z.literal(false),
    request_values_included: z.literal(false),
    reference_answers_included: z.literal(false),
    execution_authorized: z.literal(false),
    approval: z.literal(false),
    verdict: z.literal("NOT_EVALUATED"),
    receipt_hash: hash,
  })
  .strict();
export type ExportReceipt = z.infer<typeof receiptSchema>;
export function sameExportGrant(a: ExportGrant, b: ExportGrant): boolean {
  return (Object.keys(grantSchema.shape) as (keyof ExportGrant)[]).every(
    (key) => a[key] === b[key],
  );
}
export function parseExportReceipt(
  raw: unknown,
  projectId: string,
  exportId: string,
  pending?: PendingExport,
): ExportReceipt {
  const r = receiptSchema.parse(raw),
    g = r.grant;
  if (
    r.id !== exportId ||
    r.project_id !== projectId ||
    r.project_id !== g.project_id ||
    r.plan_id !== g.plan_id ||
    r.plan_hash !== g.plan_hash ||
    r.recipient_id !== g.recipient_id ||
    r.tier !== g.tier ||
    r.created_at_ms >= g.expires_at_ms ||
    r.input_set_complete !== (r.tier === "baseline_inputs") ||
    (pending &&
      (pending.id !== r.id ||
        pending.projectId !== r.project_id ||
        !sameExportGrant(pending.grant, g) ||
        r.all_frozen_samples !== pending.sampleCount ||
        r.source_plan_schema !== pending.planSchema ||
        r.software_archive_sha256 !== pending.softwareHash ||
        r.plan_id !== pending.request.plan_id ||
        r.plan_hash !== pending.request.plan_hash ||
        g.id !== pending.request.grant_id ||
        r.recipient_id !== pending.request.recipient_id ||
        r.tier !== pending.request.tier))
  )
    throw new Error("Invalid export receipt");
  return r;
}
const eventSchema = z
  .object({
    id,
    project_id: identifier,
    export_id: id,
    actor: identifier,
    action: z.enum(["export_created", "bundle_opened"]),
    sequence: z.number().int().min(1).max(2_147_483_647),
    at_ms: time,
  })
  .strict();
export type ExportAuditEvent = z.infer<typeof eventSchema>;
export function parseExportAudit(
  raw: unknown,
  receipt: ExportReceipt,
  after: number,
) {
  const page = z
    .object({
      events: z.array(eventSchema).max(100),
      next_after_sequence: z
        .number()
        .int()
        .min(1)
        .max(2_147_483_647)
        .nullable(),
    })
    .strict()
    .parse(raw);
  if (
    page.events.some(
      (e, index) =>
        e.project_id !== receipt.project_id ||
        e.export_id !== receipt.id ||
        e.actor !== receipt.grant.owner_id ||
        e.sequence !== after + index + 1,
    ) ||
    new Set(page.events.map((e) => e.id)).size !== page.events.length ||
    page.next_after_sequence !==
      (page.events.length === 100 ? page.events.at(-1)!.sequence : null)
  )
    throw new Error("Invalid export audit page");
  return page;
}
