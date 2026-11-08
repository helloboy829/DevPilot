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
  const response = await fetch(`${getBackendBaseURL()}/api/${route}`, {
    method: "GET",
    cache: "no-store",
  });
  if (!response.ok)
    await throwGatewayApiError(response, "Report export failed");
  const mime =
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  const maximum = 524288;
  if (
    response.headers.get("content-type")?.split(";")[0] !== mime ||
    response.headers.get("x-devpilot-renderer") !== "qa-docx-v1" ||
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
  const prefix = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
  if (
    prefix.length !== 4 ||
    prefix[0] !== 80 ||
    prefix[1] !== 75 ||
    prefix[2] !== 3 ||
    prefix[3] !== 4
  )
    throw new Error("Invalid report export");
  return blob;
}
