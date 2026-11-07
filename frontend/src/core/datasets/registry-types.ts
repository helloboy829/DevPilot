export type ComponentKind = "llm" | "cv" | "agent" | "model";

export interface ComponentInventory {
  schema: "component-inventory.v1";
  source_component_id: string;
  name: string;
  transport: string;
  response_mode: string;
  supports_streaming: boolean;
  validation_type: string;
  component_fingerprint: string;
}

export interface ProjectComponent {
  id: string;
  project_id: string;
  source_component_id: string;
  name_at_link: string;
  kind: ComponentKind;
}

export interface SubmissionInventory {
  id: string;
  project_id: string;
  component_id: string;
  version_label: string;
  dataset_id: string;
  dataset_revision: number;
  dataset_hash: string;
  dataset_purpose: "baseline" | "acceptance";
  component_snapshot: Omit<ComponentInventory, "component_fingerprint"> & {
    kind: ComponentKind;
  };
  scope: "inventory_only";
  submission_hash: string;
  created_by: string;
  created_at: string;
}
