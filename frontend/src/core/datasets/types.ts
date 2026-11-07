export interface EvaluationProject {
  id: string;
  name: string;
}

export interface DatasetVersion {
  id: string;
  project_id: string;
  name: string;
  purpose: "baseline" | "acceptance";
  revision: number;
  status: "draft" | "frozen";
  sample_count: number;
  content_hash: string | null;
  source: {
    label: string;
    reference: string;
    authorization_basis: string;
    attested: boolean;
  };
  frozen_by?: string | null;
  frozen_at?: string | null;
}

export interface QASample {
  sample_id: string;
  input: string;
  expected: string;
  source_ref: string;
  slice_tag: string;
}

export interface DataAuditEvent {
  id: string;
  action: string;
  actor: string;
  revision: number;
  at: string;
}
