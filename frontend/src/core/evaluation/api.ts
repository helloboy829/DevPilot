import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export async function evaluationApi<T>(
  route: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}/api/${route}`, {
    method: body === undefined && method === "POST" ? "GET" : method,
    cache: "no-store",
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok)
    await throwGatewayApiError(
      response,
      "Operation failed; check permissions and configuration",
    );
  return response.json() as Promise<T>;
}

/** Explicit version-pinned binary export; never cache, retry, or save an HTML login page. */
export async function evaluationReportDocx(route: string): Promise<Blob> {
  return reportDocx(route, "qa-docx-v1");
}

/** Independent history has a separate namespace/renderer, never the owner export. */
export async function evaluationIndependentReportDocx(
  route: string,
): Promise<Blob> {
  return reportDocx(route, "independent-qa-docx-v1");
}

/** Stored independent comparison facts; not a report/Markdown export. */
export async function evaluationIndependentRetestDocx(
  route: string,
): Promise<Blob> {
  return reportDocx(route, "independent-retest-docx-v1");
}

export async function evaluationIndependentReportPdf(
  route: string,
): Promise<Blob> {
  return reportBinary(
    route,
    "independent-qa-pdf-v1",
    "application/pdf",
    8388608,
    [37, 80, 68, 70, 45],
  );
}

export async function evaluationIndependentRetestPdf(
  route: string,
): Promise<Blob> {
  return reportBinary(
    route,
    "independent-retest-pdf-v1",
    "application/pdf",
    8388608,
    [37, 80, 68, 70, 45],
  );
}

async function reportDocx(route: string, renderer: string): Promise<Blob> {
  return reportBinary(
    route,
    renderer,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    524288,
    [80, 75, 3, 4],
  );
}

async function reportBinary(
  route: string,
  renderer: string,
  mime: string,
  maximum: number,
  signature: number[],
): Promise<Blob> {
  const response = await fetch(`${getBackendBaseURL()}/api/${route}`, {
    method: "GET",
    cache: "no-store",
  });
  if (!response.ok)
    await throwGatewayApiError(response, "Report export failed");
  if (
    response.headers.get("content-type")?.split(";")[0] !== mime ||
    response.headers.get("x-devpilot-renderer") !== renderer ||
    Number(response.headers.get("content-length")) > maximum ||
    !response.body
  )
    throw new Error("Invalid report export");
  const reader = response.body.getReader();
  const chunks: BlobPart[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximum) {
        await reader.cancel();
        throw new Error("Invalid report export");
      }
      chunks.push(new Uint8Array(value));
    }
  } finally {
    reader.releaseLock();
  }
  const blob = new Blob(chunks, { type: mime });
  const prefix = new Uint8Array(
    await blob.slice(0, signature.length).arrayBuffer(),
  );
  if (
    prefix.length !== signature.length ||
    signature.some((byte, index) => prefix[index] !== byte)
  )
    throw new Error("Invalid report export");
  return blob;
}
