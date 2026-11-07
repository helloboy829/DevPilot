import { describe, expect, test } from "@rstest/core";

import {
  EVALUATION_ASSISTANT_PRESETS,
  buildManualAssistant,
} from "@/core/agents/evaluation-presets";

describe("manual evaluation assistants", () => {
  test("offers bilingual advisory presets with no configured tool groups or skills", () => {
    expect(EVALUATION_ASSISTANT_PRESETS).toHaveLength(3);
    expect(
      new Set(EVALUATION_ASSISTANT_PRESETS.map((item) => item.id)).size,
    ).toBe(3);
    for (const preset of EVALUATION_ASSISTANT_PRESETS) {
      for (const locale of ["en-US", "zh-CN"] as const) {
        expect(preset.title[locale]).toBeTruthy();
        const request = buildManualAssistant({
          name: "My-Assistant",
          description: preset.title[locale],
          soul: preset.soul[locale],
        });
        expect(request.name).toBe("my-assistant");
        expect(request.model).toBeNull();
        expect(request.tool_groups).toEqual([]);
        expect(request.skills).toEqual([]);
        expect(request.soul).toContain(locale === "zh-CN" ? "人工" : "human");
      }
    }
  });

  test.each(["", " ../escape", "bad_name", "中文", "x".repeat(65)])(
    "rejects invalid names without echoing input: %s",
    (name) => {
      expect(() =>
        buildManualAssistant({ name, description: "", soul: "Instructions" }),
      ).toThrow("Invalid assistant fields");
    },
  );

  test("requires bounded instructions and optional bounded description", () => {
    for (const input of [
      { soul: "  ", description: "" },
      { soul: "x".repeat(12001), description: "" },
      { soul: "Instructions", description: "x".repeat(501) },
    ])
      expect(() =>
        buildManualAssistant({ name: "assistant", ...input }),
      ).toThrow("Invalid assistant fields");
    expect(
      buildManualAssistant({
        name: "  assistant  ",
        description: "  brief  ",
        soul: "  Instructions  ",
      }).description,
    ).toBe("brief");
  });
});
