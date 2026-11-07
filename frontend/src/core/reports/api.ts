import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  ReportFacts,
  ReportAdvisory,
  ReportAssistantStatus,
  ReportAssistantResult,
  ReportPreview,
  ReportTemplateSummary,
} from "./types";

export async function fetchReportTemplates(): Promise<ReportTemplateSummary[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/reports/templates`, {
    cache: "no-store",
  });
  if (!response.ok)
    await throwGatewayApiError(response, "Unable to load report templates");
  return ((await response.json()) as { templates: ReportTemplateSummary[] })
    .templates;
}

export async function generateReportPreview(
  template: ReportTemplateSummary,
  facts: ReportFacts,
  advisory?: ReportAdvisory,
): Promise<ReportPreview> {
  const response = await fetch(`${getBackendBaseURL()}/api/reports/preview`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      template_id: template.id,
      template_version: template.version,
      facts,
      ...(advisory ? { advisory } : {}),
    }),
  });
  if (!response.ok)
    await throwGatewayApiError(
      response,
      "Unable to generate report; check fields and permissions",
    );
  return response.json() as Promise<ReportPreview>;
}

export function downloadReport(preview: ReportPreview, format: "md" | "json") {
  const blob = new Blob(
    [format === "md" ? preview.markdown : JSON.stringify(preview, null, 2)],
    {
      type:
        format === "md"
          ? "text/markdown;charset=utf-8"
          : "application/json;charset=utf-8",
    },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `evaluation-report-draft.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Let the browser start the download before releasing the object URL.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function fetchReportAssistantStatus(): Promise<ReportAssistantStatus> {
  const response = await fetch(`${getBackendBaseURL()}/api/reports/assistant`, {
    cache: "no-store",
  });
  if (!response.ok)
    await throwGatewayApiError(
      response,
      "Unable to load report assistant status",
    );
  return response.json() as Promise<ReportAssistantStatus>;
}

export async function requestReportAdvice(
  template: ReportTemplateSummary,
  facts: ReportFacts,
): Promise<ReportAssistantResult> {
  const response = await fetch(`${getBackendBaseURL()}/api/reports/assistant`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      template_id: template.id,
      template_version: template.version,
      facts,
      consent: true,
    }),
  });
  if (!response.ok)
    await throwGatewayApiError(response, "Unable to request report advice");
  return response.json() as Promise<ReportAssistantResult>;
}
