import { describe, expect, it } from "@rstest/core";

import {
  assessmentIdValid,
  assessmentKey,
  parseIndependentAssessment,
  parseAssessmentHistory,
  parseAssessmentArchive,
  parseAssessmentReceipt,
  type PendingAssessment,
} from "@/core/evaluation/assessment-policy";

import {
  assessment,
  assessmentArchive,
  assessmentId,
  assessmentMetadata,
  provisionalAssessment,
} from "../../../fixtures/assessment";
const parse = (value: unknown) => parseIndependentAssessment(value, "p1", "r1");
describe("independent assessment DTO boundary", () => {
  it("accepts complete, provisional zero-threshold and historical no-criteria previews", () => {
    expect(parse(assessment()).human_pass_rate.denominator).toBe(2);
    expect(parse(provisionalAssessment()).criteria_evaluation?.status).toBe(
      "incomplete",
    );
    const old = assessment();
    delete old.criteria_evaluation;
    expect(parse(old).criteria_evaluation).toBeUndefined();
    expect(assessmentIdValid(assessmentId)).toBe(true);
    expect(assessmentIdValid("E".repeat(32))).toBe(false);
    expect(assessmentKey("a/b", "c")).not.toBe(assessmentKey("a", "b/c"));
  });
  it.each([
    { schema: "qa-human-summary.v1" },
    { scope: "verified_owner_summary" },
    { project_id: "p2" },
    { run_id: "r2" },
    { acceptance: "approved" },
    { summary_hash: "x".repeat(64) },
    { unexpected_secret: "never display" },
    {
      policy: {
        id: "owner",
        population: "all_frozen_effectiveness_samples",
        timing: "post_collection_assessment",
      },
    },
    { human_pass_rate: { numerator: 1, denominator: 1, value: 1 } },
    { counts: { pass: 2, fail: 0, uncertain: 0, unreviewed: 0 } },
    { technical_counts: { collected: 1, other: 0 } },
    { readiness: "provisional" },
    { blockers: ["technical_incomplete"] },
    { run_status: "recording" },
  ])("rejects foreign, inconsistent or overbroad preview %j", (patch) => {
    expect(() => parse({ ...assessment(), ...patch })).toThrow();
  });
  it("rejects duplicate ordinals, task IDs and inconsistent resolution bindings", () => {
    const original = assessment();
    const changed = structuredClone(original);
    changed.cases[1]!.ordinal = 1;
    expect(() => parse(changed)).toThrow();
    const duplicate = structuredClone(original);
    duplicate.cases[1]!.tasks = duplicate.cases[0]!.tasks;
    expect(() => parse(duplicate)).toThrow();
    const missing = structuredClone(original);
    missing.cases[0]!.tasks[0]!.resolution_revision = 0;
    expect(() => parse(missing)).toThrow();
    const tooMany = structuredClone(original);
    tooMany.cases[0]!.tasks = Array.from({ length: 10_001 }, (_, i) => ({
      ...original.cases[0]!.tasks[0]!,
      task_id: i.toString(16).padStart(32, "0"),
    }));
    expect(() => parse(tooMany)).toThrow();
  });
  it("rejects provisional/criteria drift and approval but never infers thresholds from a rounded rate", () => {
    const incomplete = provisionalAssessment();
    expect(() =>
      parse({
        ...incomplete,
        criteria_evaluation: {
          ...incomplete.criteria_evaluation,
          status: "met",
        },
      }),
    ).toThrow();
    expect(() =>
      parse({
        ...incomplete,
        blockers: [...incomplete.blockers, ...incomplete.blockers],
      }),
    ).toThrow();
    expect(() =>
      parse({
        ...assessment(),
        criteria_evaluation: {
          ...assessment().criteria_evaluation,
          approval: "approved",
        },
      }),
    ).toThrow();
    // This boundary checks the server DTO, not a second threshold/calculation engine.
    expect(
      parse(
        assessment({
          criteria_evaluation: {
            ...assessment().criteria_evaluation!,
            status: "not_met",
          },
        }),
      ).criteria_evaluation?.status,
    ).toBe("not_met");
  });
});
describe("immutable assessment metadata and receipt binding", () => {
  const pending: PendingAssessment = {
    id: assessmentId,
    projectId: "p1",
    runId: "r1",
    payload: {
      summary_hash: "b".repeat(64),
      expected_previous_revision: 0,
      confirmed: true,
    },
  };
  it("binds receipt to scope, requested ID, revision and viewed summary", () => {
    expect(parseAssessmentReceipt(assessmentArchive(), pending).revision).toBe(
      1,
    );
    for (const patch of [
      { id: "a".repeat(32) },
      { project_id: "p2" },
      { run_id: "r2" },
      { revision: 2 },
      { scope: "owner" },
      { acceptance: "approved" },
      { assessment: assessment({ summary_hash: "a".repeat(64) }) },
      { assessment: assessment({ project_id: "p2" }) },
    ]) {
      expect(() =>
        parseAssessmentReceipt({ ...assessmentArchive(), ...patch }, pending),
      ).toThrow();
    }
    expect(() =>
      parseAssessmentArchive(assessmentArchive(), "p1", "r1", "invalid"),
    ).toThrow();
  });
  it("requires a descending, bounded raw metadata array without duplicate IDs", () => {
    const first = assessmentMetadata();
    const second = { ...first, id: "a".repeat(32), revision: 2 };
    expect(parseAssessmentHistory([second, first], "p1", "r1")).toHaveLength(2);
    for (const rows of [
      { assessments: [] },
      [first, second],
      [first, first],
      [{ ...first, revision: 0 }],
      [{ ...first, revision: 1_001 }],
      [{ ...first, project_id: "p2" }],
      [{ ...first, run_id: "r2" }],
      Array(101).fill(first),
    ]) {
      expect(() => parseAssessmentHistory(rows, "p1", "r1")).toThrow();
    }
  });
});
