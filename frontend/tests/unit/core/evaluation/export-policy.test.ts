import { expect, it } from "@rstest/core";

import {
  parseExportCapabilities,
  parseExportPlan,
  parseExportReceipt,
  parseExportAudit,
} from "@/core/evaluation/export-policy";

import {
  exportCapabilities,
  exportGrant,
  exportPlan,
  exportReceipt,
} from "../../../fixtures/authorized-export";

it("accepts only same-project unexpired scoped policy metadata with explicit false authority", () => {
  expect(parseExportCapabilities(exportCapabilities, "p1").grants).toHaveLength(
    1,
  );
  for (const patch of [
    { project_id: "p2" },
    { execution_authorized: true },
    { approval: true },
    { enabled: false },
    { software_archive_sha256: null },
    { grants: [exportGrant, exportGrant] },
    { grants: [{ ...exportGrant, project_id: "p2" }] },
    { grants: [{ ...exportGrant, expires_at_ms: 10_000 }] },
    { grants: [{ ...exportGrant, off_platform_authorized: 1 }] },
    {
      grants: [
        { ...exportGrant, target_origin: "https://user:pass@example.test/" },
      ],
    },
    { grants: [{ ...exportGrant, recipient_id: "not-an-account" }] },
  ])
    expect(() =>
      parseExportCapabilities({ ...exportCapabilities, ...patch }, "p1"),
    ).toThrow();
  expect(
    parseExportCapabilities(
      {
        ...exportCapabilities,
        enabled: false,
        grants: [],
        software_archive_sha256: null,
      },
      "p1",
    ).enabled,
  ).toBe(false);
});
it("requires an explicitly opened exact frozen source, not latest or a changed hash", () => {
  expect(parseExportPlan(exportPlan, exportGrant).sampleCount).toBe(2);
  for (const patch of [
    { id: "other" },
    { project_id: "p2" },
    { definition_hash: "0".repeat(64) },
    { definition: { ...exportPlan.definition, dataset_purpose: "acceptance" } },
    {
      definition: { ...exportPlan.definition, limits: { mode: "performance" } },
    },
  ])
    expect(() =>
      parseExportPlan({ ...exportPlan, ...patch }, exportGrant),
    ).toThrow();
});
it("checks receipt source/grant/budget population and all non-authority flags", () => {
  const receipt = exportReceipt();
  expect(parseExportReceipt(receipt, "p1", receipt.id)).toEqual(receipt);
  for (const patch of [
    { id: "a".repeat(32) },
    { project_id: "p2" },
    { plan_hash: "0".repeat(64) },
    { tier: "skeleton" },
    { input_set_complete: false },
    { ready_for_preflight: true },
    { request_values_included: true },
    { reference_answers_included: true },
    { execution_authorized: true },
    { approval: true },
    { verdict: "PASS" },
    { created_at_ms: exportGrant.expires_at_ms },
    {
      grant: {
        ...exportGrant,
        recipient_id: "00000000-0000-0000-0000-000000000004",
      },
    },
  ])
    expect(() =>
      parseExportReceipt({ ...receipt, ...patch }, "p1", receipt.id),
    ).toThrow();
  const pending = {
    id: receipt.id,
    projectId: "p1",
    grant: exportGrant,
    sampleCount: 2,
    planSchema: "qa-json-plan.v2" as const,
    softwareHash: exportCapabilities.software_archive_sha256,
    request: {
      plan_id: "plan1",
      plan_hash: exportGrant.plan_hash,
      grant_id: exportGrant.id,
      recipient_id: exportGrant.recipient_id,
      tier: exportGrant.tier,
      confirmed: true as const,
      data_use_confirmed: true as const,
      external_controls_acknowledged: true as const,
    },
  };
  expect(parseExportReceipt(receipt, "p1", receipt.id, pending)).toEqual(
    receipt,
  );
  for (const patch of [
    { all_frozen_samples: 1 },
    { source_plan_schema: "qa-json-plan.v1" },
    { software_archive_sha256: "0".repeat(64) },
    { grant: { ...exportGrant, target_origin: "https://other.test:443" } },
  ])
    expect(() =>
      parseExportReceipt({ ...receipt, ...patch }, "p1", receipt.id, pending),
    ).toThrow();
});
it("requires ordered same-export audit pages and an exact continuation cursor", () => {
  const r = exportReceipt();
  const e = {
    id: "5".repeat(32),
    project_id: "p1",
    export_id: r.id,
    actor: exportGrant.owner_id,
    action: "export_created",
    sequence: 1,
    at_ms: 20_000,
  };
  expect(
    parseExportAudit({ events: [e], next_after_sequence: null }, r, 0).events,
  ).toEqual([e]);
  for (const patch of [
    { sequence: 2 },
    { actor: "other" },
    { export_id: "a".repeat(32) },
    { action: "approved" },
  ])
    expect(() =>
      parseExportAudit(
        { events: [{ ...e, ...patch }], next_after_sequence: null },
        r,
        0,
      ),
    ).toThrow();
  expect(() =>
    parseExportAudit({ events: [e], next_after_sequence: 1 }, r, 0),
  ).toThrow();
});
