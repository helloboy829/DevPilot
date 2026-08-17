import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  AcceptanceCriteria,
  Component,
  ComponentTestReport,
  ComponentTestRun,
  ComponentTestType,
} from "./types";

function componentTestsUrl(path: string): string {
  return `${getBackendBaseURL()}/api/component-tests${path}`;
}

export async function fetchComponents(): Promise<Component[]> {
  const response = await fetch(componentTestsUrl("/components"));
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load components: ${response.statusText}`,
    );
  }
  const payload = (await response.json()) as { components: Component[] };
  return payload.components ?? [];
}

export type ComponentPayload = {
  name: string;
  component_code?: string | null;
  transport: string;
  api_url: string;
  api_token?: string | null;
  response_mode: string;
  supports_streaming: boolean;
  validation_type: string;
  acceptance_criteria: AcceptanceCriteria;
};

export async function createComponent(
  payload: ComponentPayload,
): Promise<Component> {
  const response = await fetch(componentTestsUrl("/components"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to create component: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function updateComponent(
  componentId: string,
  payload: Partial<ComponentPayload> & { enabled?: boolean },
): Promise<Component> {
  const response = await fetch(
    componentTestsUrl(`/components/${encodeURIComponent(componentId)}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to update component: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function deleteComponent(
  componentId: string,
): Promise<{ deleted: boolean }> {
  const response = await fetch(
    componentTestsUrl(`/components/${encodeURIComponent(componentId)}`),
    { method: "DELETE" },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to delete component: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function triggerComponentRun(
  componentId: string,
  testType: ComponentTestType,
  params: Record<string, unknown>,
): Promise<ComponentTestRun> {
  const response = await fetch(
    componentTestsUrl(`/components/${encodeURIComponent(componentId)}/runs`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ test_type: testType, params }),
    },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to trigger run: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchComponentRuns(
  componentId: string,
): Promise<ComponentTestRun[]> {
  const response = await fetch(
    componentTestsUrl(`/components/${encodeURIComponent(componentId)}/runs`),
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load runs: ${response.statusText}`,
    );
  }
  const payload = (await response.json()) as { runs: ComponentTestRun[] };
  return payload.runs ?? [];
}

export async function fetchComponentRun(
  runId: string,
): Promise<ComponentTestRun> {
  const response = await fetch(
    componentTestsUrl(`/runs/${encodeURIComponent(runId)}`),
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load run: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchComponentRunReport(
  runId: string,
): Promise<ComponentTestReport> {
  const response = await fetch(
    componentTestsUrl(`/runs/${encodeURIComponent(runId)}/report`),
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load report: ${response.statusText}`,
    );
  }
  return response.json();
}
