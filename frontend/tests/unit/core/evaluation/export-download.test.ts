import { beforeEach, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));
import { fetch as fetcher } from "@/core/api/fetcher";
import { evaluationExportBundle } from "@/core/evaluation/export-download";
import { parseExportReceipt } from "@/core/evaluation/export-policy";

import { exportReceipt } from "../../../fixtures/authorized-export";
const mock = rs.mocked(fetcher),
  raw = exportReceipt();
const receipt = parseExportReceipt(raw, "p1", raw.id);
const headers = {
  "Content-Type": "application/zip",
  "X-DevPilot-Exporter": "platform-local-qa-config.v1",
  "X-DevPilot-Receipt-Hash": receipt.receipt_hash,
};
beforeEach(() => {
  mock.mockReset();
});
it("makes exactly one authenticated no-store pinned GET and returns bounded binary", async () => {
  mock.mockResolvedValue(
    new Response(new Uint8Array([80, 75, 3, 4]), { headers }),
  );
  const blob = await evaluationExportBundle(receipt);
  expect(blob.type).toBe("application/zip");
  expect(blob.size).toBe(4);
  expect(mock.mock.calls).toEqual([
    [
      `/backend/api/evaluation/projects/p1/exports/${receipt.id}/bundle?viewed_receipt_hash=${receipt.receipt_hash}&confirm_download=true`,
      { method: "GET", cache: "no-store", redirect: "error" },
    ],
  ]);
});
it("rejects HTML, wrong exporter/hash, invalid lengths, truncation and non-ZIP without retry", async () => {
  const patches: Record<string, string>[] = [
    { "Content-Type": "text/html" },
    { "X-DevPilot-Exporter": "future" },
    { "X-DevPilot-Receipt-Hash": "0".repeat(64) },
    { "Content-Length": "5" },
    { "Content-Length": "-1" },
    { "Content-Length": "NaN" },
    { "Content-Length": "4e0" },
  ];
  for (const patch of patches) {
    mock.mockResolvedValue(
      new Response(new Uint8Array([80, 75, 3, 4]), {
        headers: { ...headers, ...patch },
      }),
    );
    await expect(evaluationExportBundle(receipt)).rejects.toThrow();
  }
  for (const data of [
    [80, 75, 3],
    [80, 75, 3, 4, 0],
    [60, 104, 116, 109],
  ]) {
    mock.mockResolvedValue(new Response(new Uint8Array(data), { headers }));
    await expect(evaluationExportBundle(receipt)).rejects.toThrow();
  }
  expect(mock).toHaveBeenCalledTimes(10);
});
it("cancels oversized streams immediately and never retries failures", async () => {
  const cancel = rs.fn();
  mock.mockResolvedValue(
    new Response(
      new ReadableStream({
        start(c) {
          c.enqueue(new Uint8Array(5));
        },
        cancel,
      }),
      { headers },
    ),
  );
  await expect(evaluationExportBundle(receipt)).rejects.toThrow();
  expect(cancel).toHaveBeenCalledTimes(1);
  mock.mockResolvedValue(new Response("unavailable", { status: 503 }));
  await expect(evaluationExportBundle(receipt)).rejects.toThrow();
  expect(mock).toHaveBeenCalledTimes(2);
});
