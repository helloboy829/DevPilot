import { z } from "zod";

import {
  parseIndependentAssessment,
  type IndependentAssessment,
  type AssessmentArchive,
} from "./assessment-policy";
const hash = z.string().regex(/^[0-9a-f]{64}$/),
  id = z.string().regex(/^[0-9a-f]{32}$/),
  identifier = z.string().min(1).max(160),
  revision = z.number().int().min(1).max(1000),
  time = z.number().int().min(1).max(Number.MAX_SAFE_INTEGER);
const referenceSchema = z
  .object({
    assessment_id: id,
    assessment_revision: revision,
    assessment_hash: hash,
  })
  .strict();
export type IndependentSource = IndependentAssessment & {
  assessment_ref: z.infer<typeof referenceSchema>;
};
export type SourceReference = ReturnType<typeof sourceReference>;
export function sourceReference(s: IndependentSource) {
  return {
    run_id: s.run_id,
    summary_hash: s.summary_hash,
    ...s.assessment_ref,
  };
}
export function archivedSource(a: AssessmentArchive): IndependentSource {
  return {
    ...a.assessment,
    assessment_ref: {
      assessment_id: a.id,
      assessment_revision: a.revision,
      assessment_hash: a.assessment_hash,
    },
  };
}
const sourceSchema = z
  .record(z.unknown())
  .transform((value): IndependentSource => {
    const { assessment_ref, ...summary } = value;
    const parsed = parseIndependentAssessment(
      summary,
      String(summary.project_id),
      String(summary.run_id),
    );
    if (parsed.readiness !== "review_complete" || parsed.blockers.length)
      throw new Error("Incomplete historical source");
    return { ...parsed, assessment_ref: referenceSchema.parse(assessment_ref) };
  });
const layout = z
  .object({
    heading: z.string().min(1).max(4000),
    project: z.string().min(1).max(4000),
    notice: z.string().min(1).max(4000),
    columns: z.string().min(1).max(4000),
    sources: z.string().min(1).max(4000),
    footer: z.string().min(1).max(4000),
    criteria_heading: z.string().min(1).max(4000),
    criteria_columns: z.string().min(1).max(4000),
    criteria_notice: z.string().min(1).max(4000),
  })
  .strict();
const templateSchema = z
  .object({
    id: z.enum(["independent-qa-project-en", "independent-qa-project-zh"]),
    version: z.literal("1.0.0"),
    language: z.enum(["en", "zh"]),
    layout,
  })
  .strict()
  .refine((t) => t.id.endsWith("-" + t.language));
export type IndependentTemplate = z.infer<typeof templateSchema>;
export function parseIndependentTemplates(v: unknown) {
  const parsed = z
    .object({ templates: z.array(templateSchema).min(1).max(2) })
    .strict()
    .parse(v);
  if (
    new Set(parsed.templates.map((t) => t.id)).size !== parsed.templates.length
  )
    throw new Error("Duplicate template");
  return parsed.templates;
}
const reportMetadataSchema = z
  .object({
    id,
    project_id: identifier,
    root_id: id,
    revision,
    supersedes_id: id.nullable(),
    title: z.string().min(1).max(160),
    template_id: z.enum([
      "independent-qa-project-en",
      "independent-qa-project-zh",
    ]),
    template_version: z.literal("1.0.0"),
    created_at_ms: time,
  })
  .strict();
const retestMetadataSchema = z
  .object({
    id,
    project_id: identifier,
    component_id: identifier,
    baseline_run_id: identifier,
    retest_run_id: identifier,
    baseline_assessment_id: id,
    retest_assessment_id: id,
    baseline_label: z.string().min(1).max(160),
    retest_label: z.string().min(1).max(160),
    created_at_ms: time,
  })
  .strict();
export type ArchiveKind = "report" | "retest";
export type IndependentMetadata =
  | z.infer<typeof reportMetadataSchema>
  | z.infer<typeof retestMetadataSchema>;
export function parseIndependentHistory(
  kind: ArchiveKind,
  value: unknown,
  project: string,
): IndependentMetadata[] {
  const rows =
    kind === "report"
      ? z.array(reportMetadataSchema).max(100).parse(value)
      : z.array(retestMetadataSchema).max(100).parse(value);
  if (
    rows.some((r) => r.project_id !== project) ||
    new Set(rows.map((r) => r.id)).size !== rows.length
  )
    throw new Error("Invalid archive history");
  return rows;
}
const common = {
  id,
  project_id: identifier,
  project_name: z.string().min(1).max(1000),
  created_at_ms: time,
  acceptance: z.literal("not_approved"),
  archive_hash: hash,
};
const reportSchema = z
  .object({
    ...common,
    schema: z.literal("qa-independent-project-report-archive.v1"),
    scope: z.literal("immutable_independent_qa_report_draft"),
    root_id: id,
    revision,
    supersedes_id: id.nullable(),
    title: z.string().min(1).max(160),
    template: templateSchema,
    template_hash: hash,
    components: z.array(sourceSchema).min(1).max(10),
    markdown: z.string().min(1).max(400000),
  })
  .strict();
const transition = z.enum([
    "pass_to_pass",
    "pass_to_fail",
    "fail_to_pass",
    "fail_to_fail",
  ]),
  count = z.number().int().min(0).max(500);
// Benchmark internals remain server-owned, not a second browser comparison engine.
const benchmarkSchema = z
  .object({
    project_id: identifier,
    component_id: identifier,
    dataset_id: identifier,
    dataset_revision: z.number().int().min(1),
    dataset_hash: hash,
    dataset_purpose: z.enum(["baseline", "acceptance"]),
    binding: z
      .object({
        schema: z.literal("qa-json-binding.v1"),
        input_pointer: z.string().max(4096),
        output_pointer: z.string().max(4096),
      })
      .strict(),
    limits: z
      .object({
        mode: z.literal("effectiveness"),
        concurrency: z.number().int().min(1).max(8),
        request_count: z.number().int().min(1).max(500),
        timeout_ms: z.number().int().min(100).max(300000),
        wall_time_ms: z.number().int().min(100).max(3600000),
        max_total_body_bytes: z.number().int().min(1).max(67108864),
      })
      .strict(),
    response_mode: z.literal("json_text"),
    sample_order: z.literal("sample_id_ascending_cycle.v1"),
    evaluation_policy: z.literal("human_review_required.v1"),
    preflight: z
      .object({
        sample_count: z.number().int().min(1).max(500),
        request_count: z.number().int().min(1).max(500),
        total_body_bytes: z.number().int().min(1).max(67108864),
      })
      .strict(),
    schema: z.literal("qa-json-plan.v2").optional(),
    acceptance_criteria: z
      .object({
        schema: z.literal("qa-effectiveness-criteria.v1"),
        version_label: z.string().min(1).max(80),
        min_pass_rate_bps: z.number().int().min(0).max(10000),
      })
      .strict()
      .optional(),
    run_response_budgets: z
      .object({
        max_response_bytes: z.number().int().min(1),
        max_total_response_bytes: z.number().int().min(1),
        lease_grace_ms: z.number().int().min(1),
      })
      .strict(),
    independent_policy: z
      .object({
        id: z.literal("independent-double-blind.v1"),
        population: z.literal("all_frozen_effectiveness_samples"),
        timing: z.literal("post_collection_assessment"),
      })
      .strict(),
  })
  .strict();
const retestCase = z
  .object({
    ordinal: z.number().int().min(1).max(500),
    sample_id: identifier,
    transition,
    baseline_decision: z.enum(["pass", "fail"]),
    retest_decision: z.enum(["pass", "fail"]),
    baseline_case_hash: hash,
    retest_case_hash: hash,
    baseline_tasks: z.array(z.unknown()).max(10000),
    retest_tasks: z.array(z.unknown()).max(10000),
  })
  .strict();
const retestSchema = z
  .object({
    ...common,
    schema: z.literal("qa-independent-retest-archive.v1"),
    scope: z.literal("same_benchmark_independent_comparison"),
    component_id: identifier,
    component_name: z.string().min(1).max(1000),
    baseline: sourceSchema,
    retest: sourceSchema,
    benchmark: benchmarkSchema,
    benchmark_hash: hash,
    request_definition_changed: z.boolean(),
    transitions: z
      .object({
        pass_to_pass: count,
        pass_to_fail: count,
        fail_to_pass: count,
        fail_to_fail: count,
      })
      .strict(),
    cases: z.array(retestCase).min(1).max(500),
    pass_rate_delta: z
      .object({
        numerator: z.number().int().min(-500).max(500),
        denominator: count.min(1),
        value: z.number().min(-1).max(1),
      })
      .strict(),
  })
  .strict();
export type IndependentReport = z.infer<typeof reportSchema>;
export type IndependentRetest = z.infer<typeof retestSchema>;
export type IndependentArchive = IndependentReport | IndependentRetest;
export type ReportRequest = {
  title: string;
  template_id: string;
  template_version: string;
  sources: SourceReference[];
  supersedes_id: string | null;
  confirmed: true;
};
export type RetestRequest = {
  baseline: SourceReference;
  retest: SourceReference;
  confirmed: true;
};
export type PendingIndependentArchive = (
  | {
      kind: "report";
      request: ReportRequest;
      parent?: { id: string; root_id: string; revision: number };
    }
  | { kind: "retest"; request: RetestRequest }
) & { projectId: string; id: string };
export type PendingIndependentArchives = Map<string, PendingIndependentArchive>;
export const independentPendingKey = (project: string, kind: ArchiveKind) =>
  JSON.stringify([project, kind]);
const same = (a: unknown, b: unknown): boolean => {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
  if (Array.isArray(a) || Array.isArray(b))
    return (
      Array.isArray(a) &&
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((v, i) => same(v, b[i]))
    );
  const left = a as Record<string, unknown>,
    right = b as Record<string, unknown>;
  return (
    Object.keys(left).length === Object.keys(right).length &&
    Object.keys(left).every(
      (k) => Object.hasOwn(right, k) && same(left[k], right[k]),
    )
  );
};
/** Structural receipt checks only; integrity hashes are not signatures or browser cryptographic proof. */
export function parseIndependentArchive(
  kind: ArchiveKind,
  value: unknown,
  project: string,
  archiveId: string,
): IndependentArchive {
  const parsed =
    kind === "report" ? reportSchema.parse(value) : retestSchema.parse(value);
  if (
    parsed.project_id !== project ||
    parsed.id !== archiveId ||
    !id.safeParse(archiveId).success
  )
    throw new Error("Archive scope mismatch");
  const sources =
    "components" in parsed
      ? parsed.components
      : [parsed.baseline, parsed.retest];
  if (sources.some((s) => s.project_id !== project))
    throw new Error("Source scope mismatch");
  if ("components" in parsed) {
    if (
      new Set(sources.map((s) => s.component_id)).size !== sources.length ||
      new Set(sources.map((s) => s.run_id)).size !== sources.length ||
      (parsed.supersedes_id === null &&
        (parsed.root_id !== parsed.id || parsed.revision !== 1)) ||
      (parsed.supersedes_id !== null &&
        (parsed.revision < 2 ||
          parsed.supersedes_id === parsed.id ||
          parsed.root_id === parsed.id))
    )
      throw new Error("Invalid report revision");
  } else {
    const { baseline: a, retest: b } = parsed,
      den = a.human_pass_rate.denominator;
    if (
      a.run_id === b.run_id ||
      a.plan_id === b.plan_id ||
      a.component_id !== b.component_id ||
      a.component_id !== parsed.component_id ||
      parsed.benchmark.project_id !== project ||
      parsed.benchmark.component_id !== parsed.component_id ||
      b.human_pass_rate.denominator !== den ||
      parsed.cases.length !== den ||
      !same(a.policy, b.policy) ||
      !same(parsed.benchmark.independent_policy, a.policy) ||
      parsed.benchmark.preflight.sample_count !== den ||
      parsed.benchmark.preflight.request_count !== den ||
      parsed.benchmark.limits.request_count !== den ||
      (parsed.benchmark.schema === "qa-json-plan.v2") !==
        (parsed.benchmark.acceptance_criteria !== undefined) ||
      !same(
        parsed.benchmark.acceptance_criteria,
        a.criteria_evaluation?.criteria,
      ) ||
      !same(a.criteria_evaluation?.criteria, b.criteria_evaluation?.criteria)
    )
      throw new Error("Invalid pair");
    const totals = {
      pass_to_pass: 0,
      pass_to_fail: 0,
      fail_to_pass: 0,
      fail_to_fail: 0,
    };
    const ids = new Set<string>();
    parsed.cases.forEach((c, i) => {
      const left = a.cases[i]!,
        right = b.cases[i]!;
      if (
        c.ordinal !== i + 1 ||
        ids.has(c.sample_id) ||
        c.transition !== c.baseline_decision + "_to_" + c.retest_decision ||
        c.baseline_decision !== left.outcome ||
        c.retest_decision !== right.outcome ||
        c.baseline_case_hash !== left.case_hash ||
        c.retest_case_hash !== right.case_hash ||
        !same(c.baseline_tasks, left.tasks) ||
        !same(c.retest_tasks, right.tasks)
      )
        throw new Error("Invalid comparison case");
      ids.add(c.sample_id);
      totals[c.transition]++;
    });
    const delta = b.human_pass_rate.numerator - a.human_pass_rate.numerator;
    if (
      !same(totals, parsed.transitions) ||
      parsed.pass_rate_delta.denominator !== den ||
      parsed.pass_rate_delta.numerator !== delta ||
      Math.abs(parsed.pass_rate_delta.value - delta / den) > Number.EPSILON
    )
      throw new Error("Invalid all-sample delta");
  }
  return parsed;
}
export function parseIndependentReceipt(
  value: unknown,
  pending: PendingIndependentArchive,
) {
  const parsed = parseIndependentArchive(
    pending.kind,
    value,
    pending.projectId,
    pending.id,
  );
  if (pending.kind === "report" && "components" in parsed) {
    const p = pending.request,
      sort = (v: SourceReference[]) =>
        [...v].sort((a, b) => a.run_id.localeCompare(b.run_id));
    if (
      parsed.title !== p.title ||
      parsed.template.id !== p.template_id ||
      parsed.template.version !== p.template_version ||
      parsed.supersedes_id !== p.supersedes_id ||
      !same(sort(parsed.components.map(sourceReference)), sort(p.sources)) ||
      parsed.root_id !== (pending.parent?.root_id ?? pending.id) ||
      parsed.revision !== (pending.parent?.revision ?? 0) + 1 ||
      p.supersedes_id !== (pending.parent?.id ?? null)
    )
      throw new Error("Report request mismatch");
  } else if (pending.kind === "retest" && "baseline" in parsed) {
    if (
      !same(sourceReference(parsed.baseline), pending.request.baseline) ||
      !same(sourceReference(parsed.retest), pending.request.retest)
    )
      throw new Error("Retest request mismatch");
  } else throw new Error("Archive namespace mismatch");
  return parsed;
}
