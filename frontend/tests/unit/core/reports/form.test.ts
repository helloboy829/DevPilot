import { describe, expect, it } from "@rstest/core";

import { emptyReportForm, toReportFacts } from "@/core/reports/form";

function form() {
  return {
    ...emptyReportForm(),
    title: "Synthetic report",
    project_name: "Fictional project",
    component_name: "Demo",
    component_version: "demo",
    tester: "Demo operator",
    test_period: "Synthetic window",
    environment: "Mock",
    scope: "Synthetic cases",
    methodology: "Manual",
    evidence_notes: "Fictional reference",
    limitations: "Unverified",
    total: "7",
    passed: "3",
    failed: "1",
    errors: "1",
    pending: "1",
    not_run: "1",
  };
}

describe("manual report facts", () => {
  it("does not seed real or invented measurements", () => {
    expect(emptyReportForm().total).toBe("");
    expect(() => toReportFacts(emptyReportForm())).toThrow();
  });
  it("keeps pending and unexecuted cases in the denominator", () => {
    expect(toReportFacts(form()).effect).toEqual({
      total: 7,
      passed: 3,
      failed: 1,
      errors: 1,
      pending: 1,
      not_run: 1,
    });
  });
  it("rejects missing, fractional or inconsistent counters", () => {
    for (const total of ["", "7.5", "NaN", "Infinity", "-1", "2"]) {
      expect(() => toReportFacts({ ...form(), total })).toThrow();
    }
  });
  it("does not submit hidden results or fabricate missing performance values", () => {
    const facts = toReportFacts({
      ...form(),
      includeEffect: false,
      includePerformance: true,
      requests: "9",
      successful_requests: "6",
      concurrency: "2",
    });
    expect(facts.effect).toBeNull();
    expect(facts.performance?.latency_mean_ms).toBeNull();
    expect(facts.performance?.ttft_mean_ms).toBeNull();
    expect(facts.performance?.latency_sample_count).toBe(0);
    expect(facts.performance?.throughput_tokens_per_s).toBeNull();
  });
  it("requires a results section and explicit nonblank metadata", () => {
    expect(() => toReportFacts({ ...form(), includeEffect: false })).toThrow();
    expect(() => toReportFacts({ ...form(), evidence_notes: " " })).toThrow();
  });
});
