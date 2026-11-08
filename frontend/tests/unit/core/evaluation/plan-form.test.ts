import { expect, it } from "@rstest/core";

import { buildPlanPayload, initialPlanForm } from "@/core/evaluation/plan-form";

const request = {
  id: "r1",
  project_id: "p1",
  component_id: "c1",
  version_label: "Request v1",
  scope: "request_definition_only" as const,
  protected_hash: "a".repeat(64),
  request_template: {
    schema: "request-template.v1" as const,
    method: "POST",
    origin: "https://example.test:443",
    headers: [],
    fingerprint: "b".repeat(64),
  },
  created_by: "fixture",
  created_at: "2026-11-08T00:00:00Z",
};
const dataset = {
  id: "d1",
  project_id: "p1",
  name: "Synthetic QA",
  purpose: "baseline" as const,
  status: "frozen" as const,
  revision: 2,
  sample_count: 3,
  content_hash: "c".repeat(64),
  source: {
    label: "fixture",
    reference: "fixture:qa",
    authorization_basis: "owned synthetic",
    attested: true,
  },
};
const form = () => ({
  ...initialPlanForm(),
  versionLabel: "Plan v1",
  inputPointer: "/q",
  outputPointer: "/a",
});
function build(
  overrides = {},
  req = request,
  data = dataset,
  confirmed = true,
) {
  return buildPlanPayload(
    { ...form(), ...overrides },
    "p1",
    "c1",
    req,
    data,
    confirmed,
  );
}
it("binds immutable references, derives complete effectiveness coverage, and adds no gold or request values", () => {
  expect(build()).toEqual({
    version_label: "Plan v1",
    request_version_id: "r1",
    request_protected_hash: "a".repeat(64),
    dataset_id: "d1",
    dataset_revision: 2,
    dataset_hash: "c".repeat(64),
    binding: {
      schema: "qa-json-binding.v1",
      input_pointer: "/q",
      output_pointer: "/a",
    },
    response_mode: "json_text",
    limits: {
      mode: "effectiveness",
      concurrency: 1,
      request_count: 3,
      timeout_ms: 30000,
      wall_time_ms: 300000,
      max_total_body_bytes: 1048576,
    },
    confirmed: true,
  });
  expect(build({ requestCount: "999" }).limits.request_count).toBe(3);
});
it("preserves literal pointer spaces and permits only explicit root-string output", () => {
  expect(
    build({ inputPointer: "/ literal ", outputPointer: "/ answer " }).binding,
  ).toMatchObject({ input_pointer: "/ literal ", output_pointer: "/ answer " });
  expect(() => build({ outputPointer: "" })).toThrow();
  expect(
    build({ rootOutput: true, outputPointer: "" }).binding.output_pointer,
  ).toBe("");
});
it.each(["q", "/q~2", "/".repeat(17), "/q\n", "/" + "中".repeat(171)])(
  "rejects invalid/bounded input pointer %s",
  (inputPointer) => {
    expect(() => build({ inputPointer })).toThrow("Invalid plan settings");
  },
);
it.each(["", "0", "1.5", "1e2", " 2", "-1", "Infinity", "9007199254740992"])(
  "rejects non-strict concurrency %s",
  (concurrency) => {
    expect(() => build({ concurrency })).toThrow();
  },
);
it.each([
  { concurrency: "9" },
  { mode: "performance", concurrency: "65" },
  { mode: "performance", requestCount: "2" },
  { mode: "performance", requestCount: "10001" },
  { timeoutMs: "99" },
  { timeoutMs: "300001" },
  { wallTimeMs: "29999" },
  { wallTimeMs: "3600001" },
  { maxTotalBodyBytes: "67108865" },
  { maxTotalBodyBytes: "0" },
  { versionLabel: " " },
  { versionLabel: "x".repeat(81) },
  { versionLabel: "unsafe\nlabel" },
  { mode: "unsupported" },
])("rejects out-of-contract limits/labels %j", (overrides) =>
  expect(() => build(overrides)).toThrow(),
);
it("supports bounded performance cycling without inventing token/TTFT metrics", () => {
  expect(
    build({ mode: "performance", concurrency: "64", requestCount: "10000" })
      .limits,
  ).toMatchObject({
    mode: "performance",
    concurrency: 64,
    request_count: 10000,
  });
});
it("requires real boolean confirmation and same project/component frozen references", () => {
  expect(() => build({}, request, dataset, false)).toThrow();
  expect(() => build({}, { ...request, component_id: "other" })).toThrow();
  expect(() => build({}, { ...request, project_id: "other" })).toThrow();
  expect(() => build({}, { ...request, protected_hash: "bad" })).toThrow();
  expect(() =>
    build({}, request, { ...dataset, project_id: "other" }),
  ).toThrow();
  expect(() => build({}, request, { ...dataset, sample_count: 0 })).toThrow();
  expect(() =>
    build({}, request, { ...dataset, content_hash: "bad" }),
  ).toThrow();
  expect(() => build({}, request, { ...dataset, revision: 0 })).toThrow();
});

it("freezes explicit versioned criteria using exact hundredths of a percent, not rounded floats", () => {
  expect(
    build({
      criteriaEnabled: true,
      criteriaLabel: "Criteria v1",
      minPassPercent: "85.25",
    }).acceptance_criteria,
  ).toEqual({
    schema: "qa-effectiveness-criteria.v1",
    version_label: "Criteria v1",
    min_pass_rate_bps: 8525,
  });
  expect(build()).not.toHaveProperty("acceptance_criteria");
  for (const value of ["85.255", "1e2", "-1", "100.01", "NaN", "", " 85 "])
    expect(() =>
      build({
        criteriaEnabled: true,
        criteriaLabel: "Criteria v1",
        minPassPercent: value,
      }),
    ).toThrow();
  expect(() =>
    build({ criteriaEnabled: true, criteriaLabel: "  ", minPassPercent: "85" }),
  ).toThrow();
  expect(() =>
    build({
      mode: "performance",
      criteriaEnabled: true,
      criteriaLabel: "Criteria v1",
      minPassPercent: "85",
    }),
  ).toThrow();
});
