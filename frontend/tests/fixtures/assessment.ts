import type {
  AssessmentArchive,
  AssessmentMetadata,
  IndependentAssessment,
} from "@/core/evaluation/assessment-policy";

export const assessmentId = "e".repeat(32);
export function assessment(
  overrides: Partial<IndependentAssessment> = {},
): IndependentAssessment {
  return {
    schema: "qa-independent-assessment-preview.v1",
    scope: "verified_independent_assessment_preview",
    policy: {
      id: "independent-double-blind.v1",
      population: "all_frozen_effectiveness_samples",
      timing: "post_collection_assessment",
    },
    project_id: "p1",
    run_id: "r1",
    run_status: "recording_finished",
    component_id: "c1",
    component_name: "Synthetic independent component",
    plan_id: "plan1",
    plan_label: "Synthetic frozen plan",
    plan_hash: "a".repeat(64),
    summary_hash: "b".repeat(64),
    counts: { pass: 1, fail: 1, uncertain: 0, unreviewed: 0 },
    technical_counts: { collected: 2, other: 0 },
    human_pass_rate: { numerator: 1, denominator: 2, value: 0.5 },
    readiness: "review_complete",
    blockers: [],
    acceptance: "not_approved",
    cases: ["pass", "fail"].map((item, i) => ({
      ordinal: i + 1,
      case_hash: String(i + 1).repeat(64),
      outcome: item as "pass" | "fail",
      tasks: [
        {
          task_id: String(i + 1).repeat(32),
          subject_hash: "c".repeat(64),
          round: 1,
          task_revision: 5,
          status: "resolved",
          resolution_revision: 1,
          resolution_hash: "d".repeat(64),
        },
      ],
    })),
    criteria_evaluation: {
      scope: "effectiveness_threshold_only",
      criteria: {
        schema: "qa-effectiveness-criteria.v1",
        version_label: "frozen-1",
        min_pass_rate_bps: 5_000,
      },
      status: "met",
      blockers: [],
      approval: "not_approved",
    },
    ...overrides,
  };
}
export function assessmentArchive(
  overrides: Partial<AssessmentArchive> = {},
): AssessmentArchive {
  return {
    schema: "qa-run-assessment-revision.v1",
    scope: "immutable_independent_assessment",
    id: assessmentId,
    project_id: "p1",
    run_id: "r1",
    revision: 1,
    created_at_ms: 1_800_000_000_000,
    assessment: assessment(),
    acceptance: "not_approved",
    assessment_hash: "f".repeat(64),
    ...overrides,
  };
}
export function assessmentMetadata(
  value = assessmentArchive(),
): AssessmentMetadata {
  return {
    id: value.id,
    project_id: value.project_id,
    run_id: value.run_id,
    revision: value.revision,
    created_at_ms: value.created_at_ms,
    summary_hash: value.assessment.summary_hash,
    assessment_hash: value.assessment_hash,
  };
}
export function provisionalAssessment(): IndependentAssessment {
  const current = assessment();
  return assessment({
    counts: { pass: 0, fail: 0, uncertain: 0, unreviewed: 2 },
    technical_counts: { collected: 1, other: 1 },
    human_pass_rate: { numerator: 0, denominator: 2, value: 0 },
    readiness: "provisional",
    blockers: ["technical_incomplete", "independent_review_incomplete"],
    cases: current.cases.map((c) => ({
      ...c,
      outcome: "unreviewed",
      tasks: [],
    })),
    criteria_evaluation: {
      ...current.criteria_evaluation!,
      status: "incomplete",
      blockers: ["technical_incomplete", "independent_review_incomplete"],
      criteria: {
        ...current.criteria_evaluation!.criteria,
        min_pass_rate_bps: 0,
      },
    },
  });
}
