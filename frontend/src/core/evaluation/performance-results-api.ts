import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { evaluationApi } from "@/core/evaluation/api";

const base = (projectId: string) =>
  `evaluation/projects/${encodeURIComponent(projectId)}`;

export type PerformanceRun = {
  id: string;
  project_id: string;
  scenario_id: string;
  owner_id: string;
  scenario_hash: string;
  profile_hash: string;
  manifest_hash: string;
  population_count: number;
  status: string;
  window_start_ns: number | null;
  window_end_ns: number | null;
  created_at: string;
  finished_at: string | null;
  state_counts?: Record<string, number>;
  metrics?: PerformanceMetrics | null;
};

export type PerformanceMetrics = {
  quantile_method: string;
  cohort_count: number;
  state_counts: Record<string, number>;
  window_seconds: number;
  attempt_qps: number | null;
  success_qps: number | null;
  rate_applicability: string;
  output_token_count: number | null;
  output_token_throughput: number | null;
  token_applicability: string;
  successful_latency_ms: {
    n: number;
    max: number | null;
    p50: number | null;
    p90: number | null;
    p99: number | null;
    p99_applicability: string;
  };
  failed_latency_ms: {
    n: number;
    max: number | null;
    p50: number | null;
    p90: number | null;
    p99: number | null;
    p99_applicability: string;
  };
  censored_count: number;
  population_sha256: string;
};

export type PerformanceMetricsEnvelope = {
  schema_version: "performance-metrics.v1";
  applicability: "available" | "not_measured" | "synthetic_only";
  revision: string | null;
  metrics: PerformanceMetrics | null;
};

export function getPerformanceMetrics(projectId: string, runId: string) {
  return evaluationApi<PerformanceMetricsEnvelope>(
    `${base(projectId)}/performance-runs/${encodeURIComponent(runId)}/metrics`,
    undefined,
    "GET",
    262144,
  );
}

export type PerformanceRunPage = {
  items: PerformanceRun[];
  total: number;
  next_cursor: string | null;
};

export type PerformanceDispatch = {
  id: string;
  project_id: string;
  run_id: string;
  ordinal: number;
  dispatch_id: string;
  phase: "warmup" | "measurement";
  sample_id: string;
  iteration_index: number;
  profile_step_id: string;
  state: string;
  send_started_ns: number | null;
  finished_ns: number | null;
  elapsed_ms: number | null;
  request_bytes: number | null;
  request_sha256: string | null;
  response_status: number | null;
  response_bytes: number | null;
  response_sha256: string | null;
  response_capture_status: string | null;
  response_hash_scope: string | null;
  captured_response_bytes: number | null;
  content_type: string | null;
  content_encoding: string | null;
  output_tokens: number | null;
  token_source: string | null;
};

export type PerformanceDispatchPage = {
  dispatches: PerformanceDispatch[];
  offset: number;
  limit: number;
};

export function listPerformanceRuns(
  projectId: string,
  options: { cursor?: string; limit?: number } = {},
) {
  const query = new URLSearchParams({ limit: String(options.limit ?? 50) });
  if (options.cursor) query.set("cursor", options.cursor);
  return evaluationApi<PerformanceRunPage>(
    `${base(projectId)}/performance-runs?${query}`,
    undefined,
    "GET",
    262144,
  );
}

export const getPerformanceRun = (projectId: string, runId: string) =>
  evaluationApi<PerformanceRun>(
    `${base(projectId)}/performance-runs/${encodeURIComponent(runId)}`,
    undefined,
    "GET",
    262144,
  );

export function listPerformanceDispatches(
  projectId: string,
  runId: string,
  options: { offset?: number; limit?: number } = {},
) {
  const query = new URLSearchParams({
    offset: String(options.offset ?? 0),
    limit: String(options.limit ?? 100),
  });
  return evaluationApi<PerformanceDispatchPage>(
    `${base(projectId)}/performance-runs/${encodeURIComponent(runId)}/dispatches?${query}`,
    undefined,
    "GET",
    524288,
  );
}

export function createPerformanceEvidenceAccess(
  projectId: string,
  runId: string,
  ordinal: number,
  evidenceHash: string,
) {
  return evaluationApi<{
    access_id: string;
    expires_at_ms: number;
  }>(
    `${base(projectId)}/performance-runs/${encodeURIComponent(runId)}/dispatches/${ordinal}/evidence-access`,
    { kind: "response", evidence_hash: evidenceHash, confirmed: true },
    "POST",
    16384,
  );
}

export async function readPerformanceEvidence(
  projectId: string,
  accessId: string,
  maximumBytes: number,
): Promise<Uint8Array> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/${base(projectId)}/performance-evidence/${encodeURIComponent(accessId)}`,
    { method: "GET", cache: "no-store", redirect: "error" },
  );
  if (response.status !== 200) {
    void response.body?.cancel().catch(() => undefined);
    throw new Error("Performance response evidence is unavailable");
  }
  const mime = response.headers
    .get("content-type")
    ?.split(";")[0]
    ?.trim()
    .toLowerCase();
  const length = response.headers.get("content-length");
  if (
    mime !== "application/octet-stream" ||
    !response.body ||
    (length !== null &&
      (!/^\d+$/.test(length) || Number(length) > maximumBytes))
  ) {
    void response.body?.cancel().catch(() => undefined);
    throw new Error("Invalid performance response evidence");
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximumBytes) throw new Error("Evidence exceeds limit");
      chunks.push(value);
    }
  } catch {
    void reader.cancel().catch(() => undefined);
    throw new Error("Invalid performance response evidence");
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  chunks.forEach((chunk) => {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  });
  return bytes;
}
