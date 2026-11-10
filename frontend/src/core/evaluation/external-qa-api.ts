import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/** Explicit metadata-only calls. No retry, error-body reflection or unbounded JSON reader. */
export async function externalQAApi(
  route: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<unknown> {
  const encoded = body === undefined ? undefined : JSON.stringify(body);
  if (
    encoded !== undefined &&
    new TextEncoder().encode(encoded).byteLength > 32768
  )
    throw new Error("External metadata request too large");
  const response = await fetch(getBackendBaseURL() + "/api/" + route, {
    method: encoded === undefined ? "GET" : "PUT",
    cache: "no-store",
    ...(signal ? { signal } : {}),
    ...(encoded === undefined
      ? {}
      : { headers: { "Content-Type": "application/json" }, body: encoded }),
  });
  if (!response.ok)
    throw new Error(
      "External metadata operation unavailable; reconcile the same intake ID only",
    );
  const length = response.headers.get("content-length"),
    maximum = 262144;
  if (
    response.headers.get("content-type")?.split(";")[0]?.trim() !==
      "application/json" ||
    !response.body ||
    (length !== null &&
      (!/^(?:0|[1-9][0-9]*)$/.test(length) ||
        !Number.isSafeInteger(Number(length)) ||
        Number(length) > maximum))
  )
    throw new Error("Invalid external metadata response");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximum || chunks.length >= maximum)
        throw new Error("Invalid external metadata response");
      chunks.push(value);
    }
    if (length !== null && size !== Number(length))
      throw new Error("Invalid external metadata response");
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes),
    ) as unknown;
  } catch {
    await reader.cancel().catch(() => undefined);
    throw new Error("Invalid external metadata response");
  } finally {
    reader.releaseLock();
  }
}
