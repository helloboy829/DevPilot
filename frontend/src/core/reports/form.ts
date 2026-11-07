import {
  effectFields,
  measurementFields,
  metadataFields,
  narrativeFields,
  performanceCountFields,
  sampleFields,
  type NumericField,
  type PerformanceResults,
  type ReportFacts,
  type TextField,
} from "./types";

export type ReportForm = Record<TextField | NumericField, string> & {
  evaluation_mode: ReportFacts["evaluation_mode"];
  includeEffect: boolean;
  includePerformance: boolean;
  content_streaming: boolean;
  metric_population: PerformanceResults["metric_population"];
  token_source: PerformanceResults["token_source"];
};

export function emptyReportForm(): ReportForm {
  return {
    ...Object.fromEntries(
      [
        ...metadataFields,
        ...narrativeFields,
        ...effectFields,
        ...performanceCountFields,
        ...measurementFields,
        ...sampleFields,
      ].map((key) => [key, ""]),
    ),
    evaluation_mode: "BASELINE",
    includeEffect: true,
    includePerformance: false,
    content_streaming: false,
    metric_population: "successful_requests",
    token_source: "unavailable",
  } as ReportForm;
}

// Friendly early validation only. The backend is the authoritative validator.
export function toReportFacts(form: ReportForm): ReportFacts {
  const invalid = () => {
    throw new Error("Invalid report facts");
  };
  const text = (key: TextField) => {
    const value = form[key].trim();
    if (
      !value ||
      value.length >
        (metadataFields.includes(key as (typeof metadataFields)[number])
          ? 200
          : 2000)
    )
      invalid();
    return value;
  };
  const count = (key: NumericField, optional = false) => {
    if (!form[key].trim()) return optional ? 0 : invalid();
    const value = Number(form[key]);
    if (!Number.isSafeInteger(value) || value < 0 || value > 1e9) invalid();
    return value;
  };
  const measurement = (key: (typeof measurementFields)[number]) => {
    if (!form[key].trim()) return null;
    const value = Number(form[key]);
    if (!Number.isFinite(value) || value < 0) invalid();
    return value;
  };
  if (!form.includeEffect && !form.includePerformance) invalid();
  const effect = form.includeEffect
    ? {
        total: count("total"),
        passed: count("passed"),
        failed: count("failed"),
        errors: count("errors"),
        pending: count("pending"),
        not_run: count("not_run"),
      }
    : null;
  if (
    effect &&
    (effect.total === 0 ||
      effect.total !==
        effect.passed +
          effect.failed +
          effect.errors +
          effect.pending +
          effect.not_run)
  )
    invalid();
  const performance = form.includePerformance
    ? {
        requests: count("requests"),
        successful_requests: count("successful_requests"),
        concurrency: count("concurrency"),
        metric_population: form.metric_population,
        latency_mean_ms: measurement("latency_mean_ms"),
        latency_sample_count: count("latency_sample_count", true),
        content_streaming: form.content_streaming,
        ttft_mean_ms: measurement("ttft_mean_ms"),
        ttft_sample_count: count("ttft_sample_count", true),
        throughput_tokens_per_s: measurement("throughput_tokens_per_s"),
        token_source: form.token_source,
      }
    : null;
  return {
    ...Object.fromEntries(
      [...metadataFields, ...narrativeFields].map((key) => [key, text(key)]),
    ),
    evaluation_mode: form.evaluation_mode,
    effect,
    performance,
  } as ReportFacts;
}
