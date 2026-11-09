const snapshot = {
  scope: "execution_reservations_diagnostic_only",
  observed_at_ms: 1700000000000,
  policy_scope: "serving_process_only",
  policy: {
    enabled: false,
    max_active_runs: 2,
    max_reserved_concurrency: 8,
    max_response_bytes: 65536,
    max_reserved_body_bytes: 67108864,
    max_reserved_response_bytes: 67108864,
  },
  reservations: {
    held_runs: 3,
    reserved_concurrency: 70,
    reserved_body_bytes: 40,
    reserved_response_bytes: 80,
    deadline_reached_runs: 2,
  },
  states: {
    queued: {
      held_runs: 0,
      deadline_reached_runs: 0,
    },
    running: {
      held_runs: 1,
      deadline_reached_runs: 1,
    },
    cancel_requested: {
      held_runs: 0,
      deadline_reached_runs: 0,
    },
    collected: {
      held_runs: 1,
      deadline_reached_runs: 0,
    },
    interrupted: {
      held_runs: 1,
      deadline_reached_runs: 1,
    },
  },
  worker_liveness: "not_established",
  release_authorized: false,
  reclaim_authorized: false,
  retry_authorized: false,
  dispatch_authorized: false,
};

export default snapshot;
