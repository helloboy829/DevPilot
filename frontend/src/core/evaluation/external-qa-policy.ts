import { z } from "zod";

import {
  parseExportPlan,
  parseExportReceipt,
  type ExportReceipt,
} from "./export-policy";

const id = z.string().regex(/^[0-9a-f]{32}$/);
const identifier = z.string().regex(/^[A-Za-z0-9_-]{1,64}$/);
const hash = z.string().regex(/^[0-9a-f]{64}$/);
const time = z.number().int().min(1).max(253_402_300_799_000);
const runId = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
const count = z.number().int().min(0).max(10_000);
const bytes = z.number().int().min(0).max(67_108_864);
const hashPair = z.object({ receipt: hash, reconciliation: hash }).strict();
const lengthPair = z
  .object({
    receipt: z.number().int().min(1).max(8192),
    reconciliation: z.number().int().min(1).max(8192),
  })
  .strict();
const authority = {
  evidence_admitted: z.literal(false),
  approval_granted: z.literal(false),
  dispatch_authorized: z.literal(false),
  resend_permitted: z.literal(false),
  resume_permitted: z.literal(false),
  verdict: z.literal("NOT_EVALUATED"),
};
const common = {
  scope: z.literal("external_unverified_technical_only"),
  verdict: z.literal("NOT_EVALUATED"),
  run_id: runId,
  frozen_input_count: z.number().int().min(1).max(500),
  frozen_request_count: z.number().int().min(1).max(10_000),
  platform_provenance_verified: z.literal(false),
  resend_permitted: z.literal(false),
  resume_permitted: z.literal(false),
};
const attemptStates = z
  .object({ dispatched: count, observed: count, delivery_unknown: count })
  .strict();
const observationKinds = z
  .object({
    delivery_unknown: count,
    http_error: count,
    invalid_output: count,
    output_collected: count,
    policy_rejected: count,
    response_limit: count,
    unsupported_response: count,
  })
  .strict();
const aggregates = {
  reserved_attempt_count: count,
  unreserved_in_snapshot_count: count,
  covered_input_count: count,
  attempt_states: attemptStates,
  observation_kinds: observationKinds,
  reserved_request_bytes: bytes,
  reserved_response_bytes: bytes,
};
const claimedState = z.enum(["ready", "running", "interrupted", "collected"]);
const identitySchema = z
  .object({
    ...common,
    schema: z.literal("local-qa-run-receipt.v1"),
    receipt_kind: z.literal("pre_dispatch_identity_only"),
    manifest_fingerprint: hash,
  })
  .strict();
const summarySchema = z
  .object({
    ...common,
    ...aggregates,
    schema: z.literal("local-qa-reconciliation.v1"),
    declared_source_sha256: hash,
    state: claimedState,
    output_content_verified: z.literal(false),
  })
  .strict();
const inspectionSchema = z
  .object({
    ...authority,
    ...aggregates,
    schema: z.literal("external-qa-metadata-inspection.v1"),
    scope: z.literal("external_technical_metadata_quarantine_only"),
    original_run_id: runId,
    declared_manifest_fingerprint: hash,
    declared_raw_sha256: hashPair,
    frozen_input_count: z.number().int().min(1).max(500),
    frozen_request_count: z.number().int().min(1).max(10_000),
    claimed_state: claimedState,
    declared_byte_hashes_matched: z.literal(true),
    aggregate_coherence_checked: z.literal(true),
    platform_provenance_verified: z.literal(false),
    per_ordinal_evidence_verified: z.literal(false),
    output_content_verified: z.literal(false),
  })
  .strict();
const sourceSchema = z
  .object({
    export_receipt: z.unknown(),
    frozen_request_count: z.number().int().min(1).max(10_000),
    max_total_request_bytes: z.number().int().min(1).max(67_108_864),
  })
  .strict();
export type IntakeSource = {
  export_receipt: ExportReceipt;
  frozen_request_count: number;
  max_total_request_bytes: number;
};
export type TechnicalDocument = { raw: string; sha256: string; bytes: number };
export type IntakeExpectation = {
  source: IntakeSource;
  inspection: z.infer<typeof inspectionSchema>;
  canonical_source_sha256: z.infer<typeof hashPair>;
  raw_document_bytes: z.infer<typeof lengthPair>;
};
export type PendingIntake = IntakeExpectation & {
  id: string;
  projectId: string;
};
export type PendingIntakes = Map<string, PendingIntake>;
export const intakeIdValid = (value: string) => id.safeParse(value).success;
export const originalRunIdValid = (value: string) =>
  runId.safeParse(value).success;
const reject = () => {
  throw new Error("Invalid external technical metadata");
};
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object")
    return (
      "{" +
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([k, v]) => JSON.stringify(k) + ":" + canonical(v))
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
}
async function sha256(value: string | Uint8Array<ArrayBuffer>) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    typeof value === "string" ? new TextEncoder().encode(value) : value,
  );
  return Array.from(new Uint8Array(digest), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}
/** Flat technical schemas only: reject duplicates and non-integer JSON literals before coercion. */
function technicalJSON(raw: string): unknown {
  let at = 0;
  const space = () => {
    while (/[\t\r\n ]/.test(raw[at] ?? "x")) at++;
  };
  function string(): string {
    const match =
      /^"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/.exec(
        raw.slice(at),
      );
    if (!match) return reject();
    at += match[0].length;
    return JSON.parse(match[0]) as string;
  }
  function object(depth: number): Record<string, unknown> {
    if (depth > 2 || raw[at++] !== "{") return reject();
    const result: Record<string, unknown> = Object.create(null) as Record<
      string,
      unknown
    >;
    space();
    if (raw[at] === "}") {
      at++;
      return result;
    }
    while (at < raw.length) {
      space();
      const key = string();
      if (Object.hasOwn(result, key)) return reject();
      space();
      if (raw[at++] !== ":") return reject();
      space();
      if (raw[at] === "{") result[key] = object(depth + 1);
      else if (raw[at] === '"') result[key] = string();
      else if (raw.startsWith("true", at)) {
        result[key] = true;
        at += 4;
      } else if (raw.startsWith("false", at)) {
        result[key] = false;
        at += 5;
      } else {
        const n = /^(?:0|[1-9][0-9]{0,9})(?![0-9.eE+-])/.exec(raw.slice(at));
        if (!n) return reject();
        result[key] = Number(n[0]);
        at += n[0].length;
      }
      space();
      if (raw[at] === "}") {
        at++;
        return result;
      }
      if (raw[at++] !== ",") return reject();
    }
    return reject();
  }
  space();
  const result = object(1);
  space();
  if (at !== raw.length) return reject();
  return result;
}
export async function readTechnicalFile(
  file: Pick<File, "size" | "arrayBuffer">,
): Promise<TechnicalDocument> {
  if (!Number.isSafeInteger(file.size) || file.size < 1 || file.size > 8192)
    return reject();
  const data = new Uint8Array(await file.arrayBuffer());
  if (data.byteLength !== file.size || data.byteLength > 8192) return reject();
  const raw = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
    data,
  );
  if (raw.charCodeAt(0) === 0xfeff) return reject();
  return { raw, sha256: await sha256(data), bytes: data.byteLength };
}
function sourceMetadata(
  raw: unknown,
  project: string,
  exportId?: string,
): IntakeSource {
  const doc = sourceSchema.parse(raw);
  const candidate = z.object({ id }).parse(doc.export_receipt);
  const receipt = parseExportReceipt(
    doc.export_receipt,
    project,
    exportId ?? candidate.id,
  );
  if (
    receipt.tier !== "baseline_inputs" ||
    !receipt.input_set_complete ||
    doc.frozen_request_count < receipt.all_frozen_samples
  )
    return reject();
  return { ...doc, export_receipt: receipt };
}
export function parseIntakeSource(
  exportRaw: unknown,
  planRaw: unknown,
  project: string,
  exportId: string,
): IntakeSource {
  const receipt = parseExportReceipt(exportRaw, project, exportId);
  const plan = parseExportPlan(planRaw, receipt.grant);
  const fields = {
    dataset_id: identifier,
    dataset_revision: z.number().int().min(1),
    dataset_hash: hash,
    request_version_id: identifier,
    request_protected_hash: hash,
  };
  const frozen = z
    .object({
      dataset_id: identifier,
      request_version_id: identifier,
      definition: z.object({
        ...fields,
        limits: z.object({
          request_count: z.number().int().min(1).max(10_000),
          max_total_body_bytes: z.number().int().min(1).max(67_108_864),
        }),
      }),
    })
    .parse(planRaw);
  if (
    receipt.tier !== "baseline_inputs" ||
    !receipt.input_set_complete ||
    plan.schema !== receipt.source_plan_schema ||
    plan.sampleCount !== receipt.all_frozen_samples ||
    frozen.dataset_id !== receipt.dataset_id ||
    frozen.request_version_id !== receipt.request_version_id ||
    Object.keys(fields).some(
      (key) =>
        frozen.definition[key as keyof typeof fields] !==
        receipt[key as keyof typeof fields],
    )
  )
    return reject();
  return sourceMetadata(
    {
      export_receipt: receipt,
      frozen_request_count: frozen.definition.limits.request_count,
      max_total_request_bytes: frozen.definition.limits.max_total_body_bytes,
    },
    project,
    exportId,
  );
}
function coherent(i: z.infer<typeof inspectionSchema>, source: IntakeSource) {
  const inputs = i.frozen_input_count,
    requests = i.frozen_request_count,
    n = i.reserved_attempt_count,
    k = i.covered_input_count;
  const { dispatched, observed, delivery_unknown: unknown } = i.attempt_states;
  const kinds = i.observation_kinds;
  if (
    inputs !== source.export_receipt.all_frozen_samples ||
    requests !== source.frozen_request_count ||
    i.declared_manifest_fingerprint !==
      source.export_receipt.manifest_fingerprint ||
    n > requests ||
    i.unreserved_in_snapshot_count !== requests - n ||
    k > Math.min(inputs, n) ||
    (n === 0) !== (k === 0) ||
    n > k * Math.floor(requests / inputs) + Math.min(k, requests % inputs) ||
    (n === requests && k !== inputs) ||
    dispatched + observed + unknown !== n ||
    Object.values(kinds).reduce((a, b) => a + b, 0) !== observed + unknown ||
    kinds.delivery_unknown !== unknown ||
    (i.claimed_state === "ready" && n !== 0) ||
    (["running", "collected"].includes(i.claimed_state) && unknown > 0) ||
    (i.claimed_state === "collected" &&
      (n !== requests || observed !== requests)) ||
    i.reserved_request_bytes < n ||
    i.reserved_request_bytes >
      Math.min(67_108_864, n * 262_144, source.max_total_request_bytes) ||
    i.reserved_response_bytes < n * 2 ||
    i.reserved_response_bytes > Math.min(67_108_864, n * 1_048_577) ||
    (n > 0 && i.reserved_response_bytes % n !== 0)
  )
    return reject();
}
export async function inspectTechnicalPair(
  receipt: TechnicalDocument,
  reconciliation: TechnicalDocument,
  originalId: string,
  source: IntakeSource,
) {
  runId.parse(originalId);
  for (const doc of [receipt, reconciliation])
    if (
      doc.bytes < 1 ||
      doc.bytes > 8192 ||
      new TextEncoder().encode(doc.raw).length !== doc.bytes ||
      (await sha256(doc.raw)) !== doc.sha256
    )
      return reject();
  const r = identitySchema.parse(technicalJSON(receipt.raw)),
    s = summarySchema.parse(technicalJSON(reconciliation.raw));
  if (
    r.run_id !== originalId ||
    s.run_id !== originalId ||
    r.manifest_fingerprint !== source.export_receipt.manifest_fingerprint ||
    s.declared_source_sha256 !== r.manifest_fingerprint ||
    r.frozen_input_count !== s.frozen_input_count ||
    r.frozen_request_count !== s.frozen_request_count
  )
    return reject();
  const inspection = inspectionSchema.parse({
    schema: "external-qa-metadata-inspection.v1",
    scope: "external_technical_metadata_quarantine_only",
    original_run_id: originalId,
    declared_manifest_fingerprint: r.manifest_fingerprint,
    declared_raw_sha256: {
      receipt: receipt.sha256,
      reconciliation: reconciliation.sha256,
    },
    frozen_input_count: r.frozen_input_count,
    frozen_request_count: r.frozen_request_count,
    claimed_state: s.state,
    ...Object.fromEntries(
      Object.keys(aggregates).map((k) => [k, s[k as keyof typeof s]]),
    ),
    declared_byte_hashes_matched: true,
    aggregate_coherence_checked: true,
    platform_provenance_verified: false,
    per_ordinal_evidence_verified: false,
    output_content_verified: false,
    evidence_admitted: false,
    approval_granted: false,
    dispatch_authorized: false,
    resend_permitted: false,
    resume_permitted: false,
    verdict: "NOT_EVALUATED",
  });
  coherent(inspection, source);
  const expected: IntakeExpectation = {
    source,
    inspection,
    canonical_source_sha256: {
      receipt: await sha256(canonical(r)),
      reconciliation: await sha256(canonical(s)),
    },
    raw_document_bytes: {
      receipt: receipt.bytes,
      reconciliation: reconciliation.bytes,
    },
  };
  return {
    expected,
    body: {
      export_id: source.export_receipt.id,
      viewed_export_receipt_hash: source.export_receipt.receipt_hash,
      original_run_id: originalId,
      manifest_fingerprint: r.manifest_fingerprint,
      receipt_json: receipt.raw,
      receipt_sha256: receipt.sha256,
      reconciliation_json: reconciliation.raw,
      reconciliation_sha256: reconciliation.sha256,
      confirmed: true as const,
      technical_metadata_only_confirmed: true as const,
      untrusted_source_acknowledged: true as const,
    },
  };
}
const intakeSchema = z
  .object({
    ...authority,
    schema: z.literal("external-qa-quarantine-receipt.v1"),
    scope: z.literal("external_technical_metadata_quarantine_only"),
    id,
    project_id: identifier,
    created_at_ms: time,
    source: sourceSchema,
    source_configuration_alignment_only: z.literal(true),
    original_run_id: runId,
    inspection: inspectionSchema,
    inspection_sha256: hash,
    canonical_source_sha256: hashPair,
    raw_document_bytes: lengthPair,
    archive_hash: hash,
  })
  .strict();
export type IntakeReceipt = Awaited<ReturnType<typeof parseIntakeReceipt>>;
export async function parseIntakeReceipt(
  raw: unknown,
  project: string,
  intakeId: string,
  pending?: PendingIntake,
) {
  const r = intakeSchema.parse(raw),
    source = sourceMetadata(r.source, project),
    i = r.inspection;
  coherent(i, source);
  if (
    r.id !== intakeId ||
    r.project_id !== project ||
    r.original_run_id !== i.original_run_id ||
    r.inspection_sha256 !== (await sha256(canonical(i)))
  )
    return reject();
  if (
    pending &&
    (pending.id !== r.id ||
      pending.projectId !== project ||
      canonical(pending.source) !== canonical(source) ||
      canonical(pending.inspection) !== canonical(i) ||
      canonical(pending.raw_document_bytes) !==
        canonical(r.raw_document_bytes) ||
      canonical(pending.canonical_source_sha256) !==
        canonical(r.canonical_source_sha256))
  )
    return reject();
  // Integrity only, NOT a signature or authentication of discarded original bytes.
  const requestHash = await sha256(
    canonical({
      scope: r.scope,
      export_id: source.export_receipt.id,
      viewed_export_receipt_hash: source.export_receipt.receipt_hash,
      original_run_id: i.original_run_id,
      manifest_fingerprint: i.declared_manifest_fingerprint,
      declared_raw_sha256: i.declared_raw_sha256,
      raw_document_bytes: r.raw_document_bytes,
      confirmed: true,
      technical_metadata_only_confirmed: true,
      untrusted_source_acknowledged: true,
    }),
  );
  const { archive_hash: archiveHash, ...document } = r;
  if (
    archiveHash !==
    (await sha256(
      canonical({
        owner_id: source.export_receipt.grant.owner_id,
        request_hash: requestHash,
        document,
      }),
    ))
  )
    return reject();
  return { ...r, source };
}
const eventSchema = z
  .object({
    id,
    project_id: identifier,
    intake_id: id,
    actor: identifier,
    action: z.literal("metadata_quarantined"),
    sequence: z.number().int().min(1).max(2_147_483_647),
    at_ms: time,
  })
  .strict();
export type IntakeAuditEvent = z.infer<typeof eventSchema>;
export function parseIntakeAudit(
  raw: unknown,
  project: string,
  intakeId: string,
  after: number,
) {
  const page = z
    .object({
      events: z.array(eventSchema).max(50),
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
    !Number.isSafeInteger(after) ||
    after < 0 ||
    new Set(page.events.map((e) => e.id)).size !== page.events.length ||
    page.events.some(
      (e, index) =>
        e.project_id !== project ||
        e.intake_id !== intakeId ||
        e.sequence !== after + index + 1,
    ) ||
    page.next_after_sequence !==
      (page.events.length === 50 ? page.events.at(-1)!.sequence : null)
  )
    return reject();
  return page;
}
