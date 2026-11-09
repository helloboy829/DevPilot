import { z } from "zod";

const hash = z.string().regex(/^[0-9a-f]{64}$/);
const identifier = z.string().min(1).max(160);
const revisionId = z.string().regex(/^[0-9a-f]{32}$/);
const count = z.number().int().min(0).max(500);
const outcome = z.enum(["pass", "fail", "uncertain", "unreviewed"]);
const blocker = z.enum([
  "collection_not_finished",
  "technical_incomplete",
  "independent_review_incomplete",
  "uncertain",
  "conflicting_independent_resolutions",
]);
const taskReference = z
  .object({
    task_id: revisionId,
    subject_hash: hash,
    round: z.number().int().min(1).max(10),
    task_revision: z.number().int().min(1).max(10_000),
    status: z.enum([
      "queued",
      "in_review",
      "escalated",
      "resolved",
      "cancelled",
    ]),
    resolution_revision: z.number().int().min(0).max(10_000),
    resolution_hash: hash.nullable(),
  })
  .strict();
const criteria = z
  .object({
    scope: z.literal("effectiveness_threshold_only"),
    criteria: z
      .object({
        schema: z.literal("qa-effectiveness-criteria.v1"),
        version_label: z.string().min(1).max(80),
        min_pass_rate_bps: z.number().int().min(0).max(10_000),
      })
      .strict(),
    status: z.enum(["met", "not_met", "incomplete"]),
    blockers: z.array(blocker).max(5),
    approval: z.literal("not_approved"),
  })
  .strict();
const previewSchema = z
  .object({
    schema: z.literal("qa-independent-assessment-preview.v1"),
    scope: z.literal("verified_independent_assessment_preview"),
    policy: z
      .object({
        id: z.literal("independent-double-blind.v1"),
        population: z.literal("all_frozen_effectiveness_samples"),
        timing: z.literal("post_collection_assessment"),
      })
      .strict(),
    run_id: identifier,
    run_status: z.enum(["recording", "recording_finished", "interrupted"]),
    project_id: identifier,
    component_id: identifier,
    component_name: z.string().min(1).max(1_000),
    plan_id: identifier,
    plan_label: z.string().min(1).max(160),
    plan_hash: hash,
    summary_hash: hash,
    counts: z
      .object({ pass: count, fail: count, uncertain: count, unreviewed: count })
      .strict(),
    technical_counts: z.object({ collected: count, other: count }).strict(),
    human_pass_rate: z
      .object({
        numerator: count,
        denominator: count.min(1),
        value: z.number().min(0).max(1),
      })
      .strict(),
    readiness: z.enum(["provisional", "review_complete"]),
    blockers: z.array(blocker).max(5),
    acceptance: z.literal("not_approved"),
    cases: z
      .array(
        z
          .object({
            ordinal: z.number().int().min(1).max(500),
            case_hash: hash,
            outcome,
            tasks: z.array(taskReference).max(10_000),
          })
          .strict(),
      )
      .min(1)
      .max(500),
    criteria_evaluation: criteria.optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    const total = value.human_pass_rate.denominator;
    const counts = { pass: 0, fail: 0, uncertain: 0, unreviewed: 0 };
    const taskIds = new Set<string>();
    let taskCount = 0;
    let bad = value.cases.length !== total;
    for (const [index, item] of value.cases.entries()) {
      bad ||= item.ordinal !== index + 1;
      counts[item.outcome]++;
      for (const task of item.tasks) {
        bad ||=
          taskIds.has(task.task_id) ||
          (task.resolution_revision === 0) !== (task.resolution_hash === null);
        taskIds.add(task.task_id);
        taskCount++;
      }
    }
    bad ||= taskCount > 10_000;
    bad ||= (Object.keys(counts) as (keyof typeof counts)[]).some(
      (key) => counts[key] !== value.counts[key],
    );
    bad ||= value.human_pass_rate.numerator !== value.counts.pass;
    bad ||=
      Math.abs(value.human_pass_rate.value - value.counts.pass / total) >
      Number.EPSILON;
    bad ||=
      value.technical_counts.collected + value.technical_counts.other !== total;
    const incomplete = value.blockers.length > 0;
    bad ||=
      value.readiness !== (incomplete ? "provisional" : "review_complete");
    bad ||= new Set(value.blockers).size !== value.blockers.length;
    bad ||=
      (value.run_status !== "recording_finished") !==
      value.blockers.includes("collection_not_finished");
    bad ||=
      value.technical_counts.other > 0 !==
      value.blockers.includes("technical_incomplete");
    bad ||=
      counts.unreviewed > 0 !==
      value.blockers.includes("independent_review_incomplete");
    bad ||= counts.uncertain > 0 !== value.blockers.includes("uncertain");
    if (value.criteria_evaluation) {
      const frozen = value.criteria_evaluation;
      bad ||= (frozen.status === "incomplete") !== incomplete;
      bad ||=
        JSON.stringify(frozen.blockers) !== JSON.stringify(value.blockers);
    }
    if (bad)
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Inconsistent independent assessment",
      });
  });
const metadataSchema = z
  .object({
    id: revisionId,
    project_id: identifier,
    run_id: identifier,
    revision: z.number().int().min(1).max(1_000),
    created_at_ms: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
    summary_hash: hash,
    assessment_hash: hash,
  })
  .strict();
const archiveSchema = z
  .object({
    schema: z.literal("qa-run-assessment-revision.v1"),
    scope: z.literal("immutable_independent_assessment"),
    id: revisionId,
    project_id: identifier,
    run_id: identifier,
    revision: z.number().int().min(1).max(1_000),
    created_at_ms: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
    assessment: previewSchema,
    acceptance: z.literal("not_approved"),
    assessment_hash: hash,
  })
  .strict();

export type IndependentAssessment = z.infer<typeof previewSchema>;
export type AssessmentArchive = z.infer<typeof archiveSchema>;
export type AssessmentMetadata = z.infer<typeof metadataSchema>;
export interface AssessmentCreatePayload {
  summary_hash: string;
  expected_previous_revision: number;
  confirmed: true;
}
export interface PendingAssessment {
  id: string;
  projectId: string;
  runId: string;
  payload: AssessmentCreatePayload;
  receipt?: AssessmentArchive;
}
/** Page memory only. Do not persist evidence or pending writes in browser storage. */
export type PendingAssessments = Map<string, PendingAssessment>;
export const assessmentIdValid = (id: string) => /^[0-9a-f]{32}$/.test(id);
export const assessmentKey = (projectId: string, runId: string) =>
  JSON.stringify([projectId, runId]);

/** Fail-closed DTO checks, not cryptographic proof or a second metric/threshold engine. */
export function parseIndependentAssessment(
  value: unknown,
  projectId: string,
  runId: string,
) {
  const parsed = previewSchema.parse(value);
  if (parsed.project_id !== projectId || parsed.run_id !== runId)
    throw new Error("Assessment scope mismatch");
  return parsed;
}
export function parseAssessmentHistory(
  value: unknown,
  projectId: string,
  runId: string,
) {
  const parsed = z.array(metadataSchema).max(100).parse(value);
  const ids = new Set<string>();
  let previous = 1_001;
  for (const row of parsed) {
    if (
      row.project_id !== projectId ||
      row.run_id !== runId ||
      row.revision >= previous ||
      ids.has(row.id)
    )
      throw new Error("Invalid assessment history");
    previous = row.revision;
    ids.add(row.id);
  }
  return parsed;
}
export function parseAssessmentArchive(
  value: unknown,
  projectId: string,
  runId: string,
  id: string,
) {
  const parsed = archiveSchema.parse(value);
  if (
    !assessmentIdValid(id) ||
    parsed.id !== id ||
    parsed.project_id !== projectId ||
    parsed.run_id !== runId
  )
    throw new Error("Assessment receipt mismatch");
  parseIndependentAssessment(parsed.assessment, projectId, runId);
  return parsed;
}
export function parseAssessmentReceipt(
  value: unknown,
  pending: PendingAssessment,
) {
  const parsed = parseAssessmentArchive(
    value,
    pending.projectId,
    pending.runId,
    pending.id,
  );
  if (
    parsed.revision !== pending.payload.expected_previous_revision + 1 ||
    parsed.assessment.summary_hash !== pending.payload.summary_hash
  )
    throw new Error("Assessment request mismatch");
  return parsed;
}
