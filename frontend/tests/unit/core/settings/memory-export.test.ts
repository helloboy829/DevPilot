import { expect, test } from "@rstest/core";

import { createMemoryExportFileName } from "@/core/settings/memory-export";

test("memory export filenames use the DevPilot product name", () => {
  expect(createMemoryExportFileName("2026-11-20T01:02:03.456Z")).toBe(
    "devpilot-memory-2026-11-20T01-02-03-456Z.json",
  );
});

test("memory export filename falls back to the current time", () => {
  expect(
    createMemoryExportFileName(undefined, new Date("2026-11-20T01:02:03.456Z")),
  ).toBe("devpilot-memory-2026-11-20T01-02-03-456Z.json");
});
