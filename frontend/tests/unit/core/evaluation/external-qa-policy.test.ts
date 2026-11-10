import { expect, it, rs } from "@rstest/core";

import {
  inspectTechnicalPair,
  parseIntakeAudit,
  parseIntakeReceipt,
  parseIntakeSource,
  readTechnicalFile,
} from "@/core/evaluation/external-qa-policy";

import fixture from "../../../fixtures/synthetic-external-qa.json";

const project = fixture.receipt.project_id;
const source = () =>
  parseIntakeSource(
    fixture.export_receipt,
    fixture.plan,
    project,
    fixture.export_receipt.id,
  );
const file = (raw: string) => {
  const bytes = new TextEncoder().encode(raw);
  return { size: bytes.byteLength, arrayBuffer: async () => bytes.buffer };
};
async function prepare() {
  return inspectTechnicalPair(
    await readTechnicalFile(file(fixture.request.receipt_json)),
    await readTechnicalFile(file(fixture.request.reconciliation_json)),
    fixture.request.original_run_id,
    source(),
  );
}
it("opens the explicitly selected complete historical baseline without current-grant expiry", () => {
  const old = structuredClone(fixture.export_receipt);
  old.grant.expires_at_ms = old.created_at_ms + 1;
  expect(
    parseIntakeSource(old, fixture.plan, project, old.id).frozen_request_count,
  ).toBe(1);
});
it.each([
  "dataset_hash",
  "request_protected_hash",
  "dataset_revision",
  "request_version_id",
  "dataset_id",
])("binds the frozen source %s", (key) => {
  const changed = structuredClone(fixture.plan);
  Object.assign(changed.definition, {
    [key]: key === "dataset_revision" ? 8 : "different",
  });
  expect(() =>
    parseIntakeSource(
      fixture.export_receipt,
      changed,
      project,
      fixture.export_receipt.id,
    ),
  ).toThrow();
});
it("rejects non-complete sources and wrong project/export/schema/sample population", () => {
  for (const patch of [
    { input_set_complete: false },
    { tier: "skeleton" },
    { all_frozen_samples: 2 },
    { source_plan_schema: "qa-json-plan.v2" },
    { project_id: "other" },
    { id: "f".repeat(32) },
  ])
    expect(() =>
      parseIntakeSource(
        { ...fixture.export_receipt, ...patch },
        fixture.plan,
        project,
        fixture.export_receipt.id,
      ),
    ).toThrow();
});
it("bounds bytes BEFORE reading and validates actual length and fatal UTF-8", async () => {
  const read = rs.fn();
  await expect(
    readTechnicalFile({ size: 8193, arrayBuffer: read }),
  ).rejects.toThrow();
  expect(read).not.toHaveBeenCalled();
  await expect(
    readTechnicalFile({
      size: 1,
      arrayBuffer: async () => new Uint8Array([0xff]).buffer,
    }),
  ).rejects.toThrow();
  await expect(
    readTechnicalFile({
      size: 1,
      arrayBuffer: async () => new Uint8Array([65, 66]).buffer,
    }),
  ).rejects.toThrow();
  await expect(readTechnicalFile(file("\uFEFF{}"))).rejects.toThrow();
});
it("preserves whitespace and actual-byte hashes; coherent success is still NOT_EVALUATED", async () => {
  const result = await prepare();
  expect(result.body).toEqual(fixture.request);
  expect(result.expected.inspection).toEqual(fixture.receipt.inspection);
  expect(result.expected.canonical_source_sha256).toEqual(
    fixture.receipt.canonical_source_sha256,
  );
  expect(result.expected.raw_document_bytes).toEqual(
    fixture.receipt.raw_document_bytes,
  );
  expect(JSON.stringify(result.expected)).not.toContain("receipt_json");
  expect(JSON.stringify(result.expected)).not.toContain("reconciliation_json");
});
it.each([
  (raw: string) =>
    raw.replace(
      '"verdict":"NOT_EVALUATED"',
      '"verdict":"NOT_EVALUATED","verdict":"NOT_EVALUATED"',
    ),
  (raw: string) =>
    raw.replace('"frozen_input_count":1', '"frozen_input_count":1.0'),
  (raw: string) =>
    raw.replace('"frozen_input_count":1', '"frozen_input_count":1e0'),
  (raw: string) =>
    raw.replace('"resume_permitted":false', '"resume_permitted":true'),
  (raw: string) => raw.replace("{", '{"secret":"not metadata",'),
])(
  "rejects duplicate keys, non-integer literals, authority and extra fields",
  async (change) => {
    await expect(
      inspectTechnicalPair(
        await readTechnicalFile(file(change(fixture.request.receipt_json))),
        await readTechnicalFile(file(fixture.request.reconciliation_json)),
        fixture.request.original_run_id,
        source(),
      ),
    ).rejects.toThrow();
  },
);
it("rejects incoherent aggregates, wider ALL counts and frozen request-budget excess", async () => {
  for (const patch of [
    { covered_input_count: 0 },
    { reserved_attempt_count: 0 },
    { reserved_request_bytes: 10001 },
    { frozen_request_count: 2 },
    { output_content_verified: true },
  ]) {
    const raw = JSON.stringify({
      ...JSON.parse(fixture.request.reconciliation_json),
      ...patch,
    });
    await expect(
      inspectTechnicalPair(
        await readTechnicalFile(file(fixture.request.receipt_json)),
        await readTechnicalFile(file(raw)),
        fixture.request.original_run_id,
        source(),
      ),
    ).rejects.toThrow();
  }
});
it("strictly guards successful receipts, all source bindings and pending expected bytes", async () => {
  const prepared = await prepare();
  const pending = {
    ...prepared.expected,
    id: fixture.receipt.id,
    projectId: project,
  };
  expect(
    await parseIntakeReceipt(
      fixture.receipt,
      project,
      fixture.receipt.id,
      pending,
    ),
  ).toEqual(fixture.receipt);
  for (const patch of [
    { approval_granted: true },
    { verdict: "PASS" },
    { extra: "raw" },
    { inspection_sha256: "0".repeat(64) },
    { raw_document_bytes: { receipt: 1, reconciliation: 1 } },
    {
      canonical_source_sha256: {
        receipt: "0".repeat(64),
        reconciliation: "0".repeat(64),
      },
    },
  ])
    await expect(
      parseIntakeReceipt(
        { ...fixture.receipt, ...patch },
        project,
        fixture.receipt.id,
        pending,
      ),
    ).rejects.toThrow();
});
it("historical receipts retain ALL counts and frozen budget even without pending bytes", async () => {
  for (const patch of [
    { frozen_request_count: 2 },
    { max_total_request_bytes: 1 },
  ])
    await expect(
      parseIntakeReceipt(
        { ...fixture.receipt, source: { ...fixture.receipt.source, ...patch } },
        project,
        fixture.receipt.id,
      ),
    ).rejects.toThrow();
});
it("strict audit pages bind exact intake/project, unique IDs and contiguous sequence", () => {
  const event = {
    id: "a".repeat(32),
    project_id: project,
    intake_id: fixture.receipt.id,
    actor: "owner",
    action: "metadata_quarantined",
    sequence: 1,
    at_ms: 20000,
  };
  expect(
    parseIntakeAudit(
      { events: [event], next_after_sequence: null },
      project,
      fixture.receipt.id,
      0,
    ).events,
  ).toHaveLength(1);
  for (const value of [
    {
      events: [{ ...event, intake_id: "f".repeat(32) }],
      next_after_sequence: null,
    },
    { events: [{ ...event, sequence: 2 }], next_after_sequence: null },
    { events: [event, event], next_after_sequence: null },
    { events: [{ ...event, notes: "sensitive" }], next_after_sequence: null },
    { events: [event], next_after_sequence: 1 },
  ])
    expect(() =>
      parseIntakeAudit(value, project, fixture.receipt.id, 0),
    ).toThrow();
});

it("rejects decoded duplicate keys, nested arrays, surplus depth and noncanonical original IDs", async () => {
  const raw = fixture.request.receipt_json;
  for (const changed of [
    raw.replace('"verdict":', '"verdict":"NOT_EVALUATED","\\u0076erdict":'),
    raw.replace('"frozen_input_count":1', '"frozen_input_count":[]'),
    raw.replace("{", '{"extra":{"more":{"deep":1}},'),
  ])
    await expect(
      inspectTechnicalPair(
        await readTechnicalFile(file(changed)),
        await readTechnicalFile(file(fixture.request.reconciliation_json)),
        fixture.request.original_run_id,
        source(),
      ),
    ).rejects.toThrow();
  for (const original of [
    " " + fixture.request.original_run_id,
    fixture.request.original_run_id.replaceAll("-", ""),
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
  ])
    await expect(
      inspectTechnicalPair(
        await readTechnicalFile(file(raw)),
        await readTechnicalFile(file(fixture.request.reconciliation_json)),
        original,
        source(),
      ),
    ).rejects.toThrow();
});
it("rejects state/count/observation incoherence without reducing the ALL denominator", async () => {
  const summary = JSON.parse(fixture.request.reconciliation_json);
  for (const patch of [
    { state: "ready" },
    {
      state: "running",
      attempt_states: { dispatched: 0, observed: 0, delivery_unknown: 1 },
      observation_kinds: {
        ...summary.observation_kinds,
        output_collected: 0,
        delivery_unknown: 1,
      },
    },
    { observation_kinds: { ...summary.observation_kinds, http_error: 1 } },
    { reserved_response_bytes: 1 },
    { reserved_request_bytes: 0 },
    { unreserved_in_snapshot_count: 1 },
  ])
    await expect(
      inspectTechnicalPair(
        await readTechnicalFile(file(fixture.request.receipt_json)),
        await readTechnicalFile(file(JSON.stringify({ ...summary, ...patch }))),
        fixture.request.original_run_id,
        source(),
      ),
    ).rejects.toThrow();
});
