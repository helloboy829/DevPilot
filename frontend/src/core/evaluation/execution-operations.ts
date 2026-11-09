import { z } from "zod";

import { fetch as authenticatedFetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export const reservationStates = [
  "queued",
  "running",
  "cancel_requested",
  "collected",
  "interrupted",
] as const;
const count = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const stateCounts = z
  .object({ held_runs: count, deadline_reached_runs: count })
  .strict();
const schema = z
  .object({
    scope: z.literal("execution_reservations_diagnostic_only"),
    observed_at_ms: count,
    policy_scope: z.literal("serving_process_only"),
    policy: z
      .object({
        enabled: z.boolean(),
        max_active_runs: z.number().int().min(1).max(32),
        max_reserved_concurrency: z.number().int().min(1).max(64),
        max_response_bytes: z.number().int().min(1).max(1_048_576),
        max_reserved_body_bytes: z.number().int().min(1).max(67_108_864),
        max_reserved_response_bytes: z.number().int().min(2).max(67_108_864),
      })
      .strict(),
    reservations: z
      .object({
        held_runs: count,
        reserved_concurrency: count,
        reserved_body_bytes: count,
        reserved_response_bytes: count,
        deadline_reached_runs: count,
      })
      .strict(),
    states: z
      .object({
        queued: stateCounts,
        running: stateCounts,
        cancel_requested: stateCounts,
        collected: stateCounts,
        interrupted: stateCounts,
      })
      .strict(),
    worker_liveness: z.literal("not_established"),
    release_authorized: z.literal(false),
    reclaim_authorized: z.literal(false),
    retry_authorized: z.literal(false),
    dispatch_authorized: z.literal(false),
  })
  .strict();
export type ReservationSnapshot = z.infer<typeof schema>;
const safeError = () => new Error("Reservation diagnostics unavailable");

export function parseReservationSnapshot(value: unknown): ReservationSnapshot {
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw safeError();
  const data = parsed.data;
  let held = 0n;
  let deadline = 0n;
  for (const state of reservationStates) {
    const item = data.states[state];
    if (item.deadline_reached_runs > item.held_runs) throw safeError();
    held += BigInt(item.held_runs);
    deadline += BigInt(item.deadline_reached_runs);
  }
  if (
    held !== BigInt(data.reservations.held_runs) ||
    deadline !== BigInt(data.reservations.deadline_reached_runs)
  )
    throw safeError();
  // Occupancy can exceed this process's current policy. Never clamp or infer free quota.
  return data;
}

const maxBytes = 16_384;
export async function loadReservationSnapshot(
  signal: AbortSignal,
): Promise<ReservationSnapshot> {
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    const response = await authenticatedFetch(
      `${getBackendBaseURL()}/api/evaluation/operations/reservations`,
      { method: "GET", cache: "no-store", signal },
    );
    if (
      !response.ok ||
      response.headers
        .get("content-type")
        ?.split(";")[0]
        ?.trim()
        .toLowerCase() !== "application/json"
    ) {
      void response.body?.cancel().catch(() => undefined);
      throw safeError();
    }
    const length = response.headers.get("content-length");
    if (
      length !== null &&
      (!/^\d+$/.test(length) || Number(length) > maxBytes)
    ) {
      void response.body?.cancel().catch(() => undefined);
      throw safeError();
    }
    if (!response.body) throw safeError();
    reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let size = 0;
    let text = "";
    while (true) {
      signal.throwIfAborted();
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) throw safeError();
      text += decoder.decode(value, { stream: true });
    }
    signal.throwIfAborted();
    text += decoder.decode();
    return parseReservationSnapshot(JSON.parse(text));
  } catch {
    if (reader) void reader.cancel().catch(() => undefined);
    throw safeError();
  } finally {
    reader?.releaseLock();
  }
}
