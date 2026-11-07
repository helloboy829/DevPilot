/** Write-only values: page memory and the authenticated encrypted-save boundary only. */
export interface RequestDefinition {
  method: string;
  url: string;
  headers: string[][];
  body: string;
}

/** Public metadata only; never add ciphertext or complete request values here. */
export interface RequestVersionMetadata {
  id: string;
  project_id: string;
  component_id: string;
  version_label: string;
  scope: "request_definition_only";
  request_template: {
    schema: "request-template.v1";
    method: string;
    origin: string;
    headers: string[][];
    fingerprint: string;
  };
  protected_hash: string;
  created_by: string;
  created_at: string;
}
