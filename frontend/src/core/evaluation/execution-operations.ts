import { z } from "zod";

import { fetch as authenticatedFetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import { readBoundedJSON } from "./bounded-json";

export const reservationStates = [
  "queued",
  "running",
  "cancel_requested",
  "collected",
  "interrupted",
] as const;
export const safetyStates = [
  "queued_ready",
  "queued_deadline_reached",
  "running_within_deadline",
  "running_deadline_reached",
  "cancel_requested_pending",
  "interrupted_terminal",
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
    safety: z
      .object({
        scope: z.literal("aggregate_held_reservation_states"),
        states: z
          .object({
            queued_ready: count,
            queued_deadline_reached: count,
            running_within_deadline: count,
            running_deadline_reached: count,
            cancel_requested_pending: count,
            interrupted_terminal: count,
          })
          .strict(),
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
  const safety = data.safety.states;
  if (
    BigInt(safety.queued_ready) + BigInt(safety.queued_deadline_reached) !==
      BigInt(data.states.queued.held_runs) ||
    safety.queued_deadline_reached !==
      data.states.queued.deadline_reached_runs ||
    BigInt(safety.running_within_deadline) +
      BigInt(safety.running_deadline_reached) !==
      BigInt(data.states.running.held_runs) ||
    safety.running_deadline_reached !==
      data.states.running.deadline_reached_runs ||
    safety.cancel_requested_pending !==
      data.states.cancel_requested.held_runs ||
    safety.interrupted_terminal !== data.states.interrupted.held_runs
  )
    throw safeError();
  const safetyHeld = safetyStates.reduce(
    (total, state) => total + BigInt(safety[state]),
    0n,
  );
  if (
    safetyHeld + BigInt(data.states.collected.held_runs) !==
    BigInt(data.reservations.held_runs)
  )
    throw safeError();
  // Occupancy can exceed this process's current policy. Never clamp or infer free quota.
  return data;
}

const maxBytes = 16_384;
export async function loadReservationSnapshot(
  signal: AbortSignal,
): Promise<ReservationSnapshot> {
  try {
    const response = await authenticatedFetch(
      `${getBackendBaseURL()}/api/evaluation/operations/reservations`,
      { method: "GET", cache: "no-store", signal },
    );
    return parseReservationSnapshot(
      await readBoundedJSON(response, signal, maxBytes, safeError),
    );
  } catch {
    throw safeError();
  }
}
