import { expect, it } from "@rstest/core";

import {
  parseIndependentArchive,
  parseIndependentReceipt,
  sourceReference,
} from "@/core/evaluation/independent-archive-policy";

import {
  independentReport,
  independentRetest,
} from "../../../fixtures/independent-archive";
it("accepts separate pinned namespaces and all frozen sample denominators", () => {
  expect(
    parseIndependentArchive("report", independentReport(), "p1", "a".repeat(32))
      .acceptance,
  ).toBe("not_approved");
  expect(
    parseIndependentArchive("retest", independentRetest(), "p1", "a".repeat(32))
      .acceptance,
  ).toBe("not_approved");
});
it("rejects legacy, foreign, provisional, extra and inconsistent denominators", () => {
  for (const patch of [
    { schema: "qa-project-report-archive.v1" },
    { scope: "immutable_qa_report_draft" },
    { project_id: "p2" },
    { acceptance: "approved" },
    { gold: "secret" },
  ])
    expect(() =>
      parseIndependentArchive(
        "report",
        { ...independentReport(), ...patch },
        "p1",
        "a".repeat(32),
      ),
    ).toThrow();
  for (const patch of [
    { readiness: "provisional" },
    { human_pass_rate: { numerator: 1, denominator: 1, value: 1 } },
    {
      assessment_ref: {
        assessment_id: "e".repeat(32),
        assessment_revision: true,
        assessment_hash: "f".repeat(64),
      },
    },
  ]) {
    const r = independentReport();
    expect(() =>
      parseIndependentArchive(
        "report",
        { ...r, components: [{ ...r.components[0], ...patch }] },
        "p1",
        r.id,
      ),
    ).toThrow();
  }
});
it("binds every request source, title, template, parent revision and pending ID", () => {
  const report = independentReport();
  const pending = {
    kind: "report" as const,
    projectId: "p1",
    id: report.id,
    request: {
      title: report.title,
      template_id: report.template.id,
      template_version: report.template.version,
      supersedes_id: null,
      sources: report.components.map(sourceReference),
      confirmed: true as const,
    },
  };
  expect(parseIndependentReceipt(report, pending).id).toBe(report.id);
  for (const patch of [
    { title: "changed" },
    { root_id: "b".repeat(32) },
    { revision: 2 },
    {
      components: [
        {
          ...report.components[0],
          assessment_ref: {
            ...report.components[0]!.assessment_ref,
            assessment_revision: 2,
          },
        },
      ],
    },
  ])
    expect(() =>
      parseIndependentReceipt({ ...report, ...patch }, pending),
    ).toThrow();
});
it("checks retest transitions, decisions, case commitments, all-sample delta and pairing", () => {
  const r = independentRetest();
  const pending = {
    kind: "retest" as const,
    projectId: "p1",
    id: r.id,
    request: {
      baseline: sourceReference(r.baseline),
      retest: sourceReference(r.retest),
      confirmed: true as const,
    },
  };
  expect(parseIndependentReceipt(r, pending).id).toBe(r.id);
  for (const patch of [
    { transitions: { ...r.transitions, fail_to_pass: 1 } },
    { pass_rate_delta: { numerator: 1, denominator: 2, value: 0.5 } },
    {
      cases: [
        { ...r.cases[0], sample_id: "s1" },
        { ...r.cases[1], sample_id: "s1" },
      ],
    },
    { retest: { ...r.retest, run_id: "r1" } },
  ])
    expect(() =>
      parseIndependentArchive("retest", { ...r, ...patch }, "p1", r.id),
    ).toThrow();
});

it("rejects contradictory benchmark criteria, schema, population and policy receipts", () => {
  const r = independentRetest();
  for (const patch of [
    { schema: undefined },
    { acceptance_criteria: undefined },
    {
      acceptance_criteria: {
        ...r.benchmark.acceptance_criteria,
        min_pass_rate_bps: 0,
      },
    },
    { preflight: { ...r.benchmark.preflight, sample_count: 1 } },
    { preflight: { ...r.benchmark.preflight, request_count: 1 } },
    { limits: { ...r.benchmark.limits, request_count: 1 } },
  ])
    expect(() =>
      parseIndependentArchive(
        "retest",
        { ...r, benchmark: { ...r.benchmark, ...patch } },
        "p1",
        r.id,
      ),
    ).toThrow();
});

it("binds successor receipts to the opened parent and leaves old receipts immutable", () => {
  const old = independentReport("b".repeat(32));
  const successor = {
    ...independentReport(),
    root_id: old.id,
    revision: 2,
    supersedes_id: old.id,
  };
  const pending = {
    kind: "report" as const,
    projectId: "p1",
    id: successor.id,
    parent: { id: old.id, root_id: old.root_id, revision: old.revision },
    request: {
      title: successor.title,
      template_id: successor.template.id,
      template_version: successor.template.version,
      supersedes_id: old.id,
      sources: successor.components.map(sourceReference),
      confirmed: true as const,
    },
  };
  expect(parseIndependentReceipt(successor, pending).id).toBe(successor.id);
  for (const patch of [
    { root_id: "c".repeat(32) },
    { revision: 3 },
    { supersedes_id: "c".repeat(32) },
  ])
    expect(() =>
      parseIndependentReceipt({ ...successor, ...patch }, pending),
    ).toThrow();
  expect(parseIndependentArchive("report", old, "p1", old.id).id).toBe(old.id);
});
