import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { evaluationApi } from "@/core/evaluation/api";
import type {
  ProjectList,
  ResultCase,
  ResultPage,
  ResultRun,
} from "@/core/evaluation/result-types";

const base = (projectId: string) =>
  `evaluation/projects/${encodeURIComponent(projectId)}`;

export async function evaluationResultApi<T>(route: string): Promise<T> {
  return evaluationApi<T>(route, undefined, "GET", 262144);
}

export const listResultProjects = () =>
  evaluationResultApi<ProjectList>("evaluation/projects");

export function listResultRuns(
  projectId: string,
  options: {
    cursor?: string;
    component_id?: string;
    dataset_id?: string;
    status?: string;
  } = {},
) {
  const query = new URLSearchParams({ limit: "50" });
  Object.entries(options).forEach(
    ([key, value]) => value && query.set(key, value),
  );
  return evaluationResultApi<ResultPage<ResultRun>>(
    `${base(projectId)}/runs?${query}`,
  );
}

export const getResultRun = (projectId: string, runId: string) =>
  evaluationResultApi<ResultRun>(
    `${base(projectId)}/runs/${encodeURIComponent(runId)}`,
  );

export function listResultCases(
  projectId: string,
  runId: string,
  options: {
    cursor?: string;
    integrity_status?: string;
    dispatch_state?: string;
    kind?: string;
    http_status?: string;
    reference_status?: string;
  } = {},
) {
  const query = new URLSearchParams({ limit: "50" });
  Object.entries(options).forEach(
    ([key, value]) => value && query.set(key, value),
  );
  return evaluationResultApi<ResultPage<ResultCase>>(
    `${base(projectId)}/runs/${encodeURIComponent(runId)}/cases?${query}`,
  );
}

export const getResultCase = (
  projectId: string,
  runId: string,
  caseId: string,
) =>
  evaluationResultApi<ResultCase>(
    `${base(projectId)}/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}`,
  );

export async function createResponseEvidenceAccess(
  projectId: string,
  runId: string,
  ordinal: number,
  evidenceHash: string,
): Promise<{
  access_id: string;
  evidence_kind: "response";
  expires_at_ms: number;
}> {
  const route = `${base(projectId)}/review-runs/${encodeURIComponent(runId)}/cases/${ordinal}/evidence-access`;
  return evaluationApi(
    route,
    { kind: "response", evidence_hash: evidenceHash, confirmed: true },
    "POST",
    16384,
  );
}

export async function readResponseEvidence(
  projectId: string,
  accessId: string,
  maximumBytes: number,
): Promise<Uint8Array> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/${base(projectId)}/evidence/${encodeURIComponent(accessId)}`,
    { method: "GET", cache: "no-store", redirect: "error" },
  );
  if (response.status !== 200) {
    void response.body?.cancel().catch(() => undefined);
    throw new Error("Response evidence is unavailable");
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
    throw new Error("Invalid response evidence");
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximumBytes) throw new Error("Invalid response evidence");
      chunks.push(value);
    }
  } catch {
    void reader.cancel().catch(() => undefined);
    throw new Error("Invalid response evidence");
  } finally {
    reader.releaseLock();
  }
  const result = new Uint8Array(size);
  let offset = 0;
  chunks.forEach((chunk) => {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  });
  return result;
}
