import { evaluationApi } from "@/core/evaluation/api";

export type MaterialBatchSummary = {
  id: string;
  name: string;
  status: string;
  component_count: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

export type MaterialBatchDetail = MaterialBatchSummary & {
  components: {
    component_id: string;
    name: string;
    kind: string;
    purpose: string;
    status: string;
    reason: string | null;
    artifact_ids: string[];
  }[];
  artifacts: {
    id: string;
    file_name: string;
    authorization_basis: string;
    purpose: string;
    sensitivity: string;
    retention_until: string;
    status: string;
    size_bytes: number | null;
    created_at: string;
    uploaded_at: string | null;
    parse_status: string;
    parse_block_count: number | null;
    parsed_at: string | null;
  }[];
};

export function listMaterialBatches() {
  return evaluationApi<{ batches: MaterialBatchSummary[] }>(
    "evaluation/material-batches?limit=100&offset=0",
    undefined,
    "GET",
    262144,
  );
}

export function getMaterialBatch(batchId: string) {
  return evaluationApi<MaterialBatchDetail>(
    `evaluation/material-batches/${encodeURIComponent(batchId)}`,
    undefined,
    "GET",
    262144,
  );
}
