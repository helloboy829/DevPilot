const mime = (response: Response) =>
  response.headers.get("content-type")?.split(";")[0]?.trim().toLowerCase();

/**
 * Reads one bounded, strict UTF-8 JSON response without exposing server details.
 * Callers own the fixed failure message and schema validation.
 */
export async function readBoundedJSON(
  response: Response,
  signal: AbortSignal,
  maxBytes: number,
  fail: () => Error,
): Promise<unknown> {
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    if (!response.ok || mime(response) !== "application/json") {
      void response.body?.cancel().catch(() => undefined);
      throw fail();
    }
    const length = response.headers.get("content-length");
    if (
      length !== null &&
      (!/^\d+$/.test(length) || Number(length) > maxBytes)
    ) {
      void response.body?.cancel().catch(() => undefined);
      throw fail();
    }
    if (!response.body) throw fail();
    reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let size = 0;
    let text = "";
    while (true) {
      signal.throwIfAborted();
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) throw fail();
      text += decoder.decode(value, { stream: true });
    }
    signal.throwIfAborted();
    text += decoder.decode();
    return JSON.parse(text);
  } catch {
    if (reader) void reader.cancel().catch(() => undefined);
    throw fail();
  } finally {
    reader?.releaseLock();
  }
}
