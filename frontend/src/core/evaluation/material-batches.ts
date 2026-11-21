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

export type MaterialPreviewResult = {
  operation_id: string;
  parse_status: "parsed" | "blocked";
  parser_version: string;
  blocks: { text: string; source_location: string }[];
  reason: string | null;
  result_hash: string;
};

export type MaterialPreviewReceipt = {
  operation_id: string;
  parse_status: "parsed" | "blocked";
  parser_version: string;
  result_hash: string;
  block_count: number;
  reason: string | null;
  created_at: string;
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

export function previewMaterialAttachment(
  batchId: string,
  artifactId: string,
  operationId: string,
) {
  return evaluationApi<MaterialPreviewResult>(
    `evaluation/material-batches/${encodeURIComponent(batchId)}/attachments/${encodeURIComponent(artifactId)}/preview`,
    { operation_id: operationId, open_content: true },
    "POST",
    4 * 1024 * 1024,
  );
}

export function getMaterialPreviewReceipt(operationId: string) {
  return evaluationApi<MaterialPreviewReceipt>(
    `evaluation/material-batches/previews/${encodeURIComponent(operationId)}`,
    undefined,
    "GET",
    16384,
  );
}
