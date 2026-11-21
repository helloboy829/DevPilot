export type ResultRun = {
  run_id: string;
  project_id: string;
  plan_id: string;
  component_id: string;
  dataset_id: string;
  status: string;
  started_at_ms: number;
  finished_at_ms: number | null;
  total: number;
  request_count: number;
  concurrency: number;
  verdict: string;
  blockers: string[];
  technical_counts: Record<string, number>;
};

export type ResultCase = {
  case_id: string;
  ordinal: number;
  integrity_status: string;
  reference_status: string;
  dispatch_state: string | null;
  kind: string | null;
  http_status: number | null;
  latency_ms: number | null;
  response_bytes: number | null;
  output_evidence: { available: boolean } | null;
  response_evidence: {
    status: string;
    hash_scope: string;
    sha256: string | null;
    captured_bytes: number | null;
    observed_bytes: number | null;
    content_type: string | null;
  } | null;
  output?: string | null;
};

export type ResultPage<T> = {
  scope: string;
  run_id?: string;
  snapshot_hash?: string;
  result_version?: string;
  total: number;
  matched_total: number;
  items: T[];
  next_cursor: string | null;
};

export type ProjectList = { projects: { id: string; name: string }[] };
