import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ExportReceipt } from "./export-policy";

/** One explicit, bounded download. No ZIP hash/provenance or execution claim. */
export async function evaluationExportBundle(
  receipt: ExportReceipt,
): Promise<Blob> {
  const route = `evaluation/projects/${encodeURIComponent(receipt.project_id)}/exports/${receipt.id}/bundle`;
  const query = new URLSearchParams({
    viewed_receipt_hash: receipt.receipt_hash,
    confirm_download: "true",
  });
  const response = await fetch(`${getBackendBaseURL()}/api/${route}?${query}`, {
    method: "GET",
    cache: "no-store",
    redirect: "error",
  });
  if (!response.ok)
    await throwGatewayApiError(response, "Configuration download failed");
  const length = response.headers.get("content-length");
  if (
    receipt.bundle_bytes < 4 ||
    receipt.bundle_bytes > 5_242_880 ||
    response.headers.get("content-type")?.split(";")[0] !== "application/zip" ||
    response.headers.get("x-devpilot-exporter") !==
      "platform-local-qa-config.v1" ||
    response.headers.get("x-devpilot-receipt-hash") !== receipt.receipt_hash ||
    (length !== null &&
      (!/^[0-9]+$/.test(length) || Number(length) !== receipt.bundle_bytes)) ||
    !response.body
  ) {
    await response.body?.cancel();
    throw new Error("Invalid configuration bundle");
  }
  const reader = response.body.getReader(),
    chunks: BlobPart[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > receipt.bundle_bytes)
        throw new Error("Invalid configuration bundle");
      chunks.push(new Uint8Array(value));
    }
  } catch {
    try {
      await reader.cancel();
    } catch {
      /* Preserve the failed download, never retry. */
    }
    throw new Error("Invalid configuration bundle");
  } finally {
    reader.releaseLock();
  }
  const blob = new Blob(chunks, { type: "application/zip" });
  const magic = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
  if (
    size !== receipt.bundle_bytes ||
    [80, 75, 3, 4].some((n, i) => magic[i] !== n)
  )
    throw new Error("Invalid configuration bundle");
  return blob;
}
