const admission = {
  schema: "qa-scheduling-admission.v1",
  scope: "qa_scheduling_admission_diagnostic_only",
  scheduler_scope: "component_tests_only",
  qa_chain_admitted: false,
  dispatch_authorized: false,
  release_authorized: false,
  blockers: [
    "no_versioned_admission_contract",
    "scheduler_not_bound_to_qa_execution",
    "worker_liveness_not_established",
  ],
};
export default admission;
