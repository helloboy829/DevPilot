import { z } from "zod";

import { fetch as authenticatedFetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import { readBoundedJSON } from "./bounded-json";

const blocker = z.enum([
  "no_versioned_admission_contract",
  "scheduler_not_bound_to_qa_execution",
  "worker_liveness_not_established",
]);
const schema = z
  .object({
    schema: z.literal("qa-scheduling-admission.v1"),
    scope: z.literal("qa_scheduling_admission_diagnostic_only"),
    scheduler_scope: z.literal("component_tests_only"),
    qa_chain_admitted: z.literal(false),
    dispatch_authorized: z.literal(false),
    release_authorized: z.literal(false),
    blockers: z.array(blocker).max(3),
  })
  .strict();
export type SchedulingAdmission = z.infer<typeof schema>;
const safeError = () =>
  new Error("Scheduling admission diagnostics unavailable");

export function parseSchedulingAdmission(value: unknown): SchedulingAdmission {
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw safeError();
  if (new Set(parsed.data.blockers).size !== parsed.data.blockers.length)
    throw safeError();
  return parsed.data;
}

const maxBytes = 16_384;
export async function loadSchedulingAdmission(
  signal: AbortSignal,
): Promise<SchedulingAdmission> {
  try {
    const response = await authenticatedFetch(
      `${getBackendBaseURL()}/api/evaluation/operations/scheduling-admission`,
      { method: "GET", cache: "no-store", signal },
    );
    return parseSchedulingAdmission(
      await readBoundedJSON(response, signal, maxBytes, safeError),
    );
  } catch {
    throw safeError();
  }
}
