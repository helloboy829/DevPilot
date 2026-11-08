/** Definition metadata only: never an execution approval or a result. */
export interface PlanLimits {
  mode: "effectiveness" | "performance";
  concurrency: number;
  request_count: number;
  timeout_ms: number;
  wall_time_ms: number;
  max_total_body_bytes: number;
}
export interface EffectivenessCriteria {
  schema: "qa-effectiveness-criteria.v1";
  version_label: string;
  min_pass_rate_bps: number;
}
export interface PlanCreate {
  acceptance_criteria?: EffectivenessCriteria;
  version_label: string;
  request_version_id: string;
  request_protected_hash: string;
  dataset_id: string;
  dataset_revision: number;
  dataset_hash: string;
  binding: {
    schema: "qa-json-binding.v1";
    input_pointer: string;
    output_pointer: string;
  };
  response_mode: "json_text";
  limits: PlanLimits;
  confirmed: true;
}
export interface FrozenPlan {
  id: string;
  project_id: string;
  component_id: string;
  request_version_id: string;
  dataset_id: string;
  version_label: string;
  scope: "frozen_definition_only";
  definition_hash: string;
  definition: Omit<PlanCreate, "confirmed"> & {
    schema: "qa-json-plan.v1" | "qa-json-plan.v2";
    scope: "frozen_definition_only";
    project_id: string;
    component_id: string;
    request_template_fingerprint: string;
    dataset_purpose: "baseline" | "acceptance";
    sample_order: "sample_id_ascending_cycle.v1";
    evaluation_policy: "human_review_required.v1";
    preflight: {
      sample_count: number;
      request_count: number;
      total_body_bytes: number;
    };
  };
  created_at: string;
  created_by: string;
}
