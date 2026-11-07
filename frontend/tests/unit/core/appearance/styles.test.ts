import { readFileSync } from "node:fs";

import { describe, expect, it } from "@rstest/core";

import {
  WORKSPACE_STYLES,
  normalizeWorkspaceStyle,
} from "@/core/appearance/styles";

describe("workspace style preferences", () => {
  it("offers five distinct, bilingual styles", () => {
    expect(WORKSPACE_STYLES).toHaveLength(5);
    expect(new Set(WORKSPACE_STYLES.map((style) => style.id)).size).toBe(5);
    for (const style of WORKSPACE_STYLES) {
      expect(normalizeWorkspaceStyle(style.id)).toBe(style.id);
      expect(style.name["zh-CN"]).toBeTruthy();
      expect(style.name["en-US"]).toBeTruthy();
    }
  });
  it("rejects invalid or stale preferences instead of injecting class names", () => {
    for (const value of [
      null,
      undefined,
      "",
      "unknown",
      "__proto__",
      "dark",
      "console foo",
    ])
      expect(normalizeWorkspaceStyle(value)).toBe("console");
  });
});

function luminance(hex: string) {
  const rgb = hex
    .slice(1)
    .match(/../g)!
    .map((part) => parseInt(part, 16) / 255)
    .map((value) =>
      value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
    );
  return rgb[0]! * 0.2126 + rgb[1]! * 0.7152 + rgb[2]! * 0.0722;
}
function contrast(a: string, b: string) {
  const x = luminance(a),
    y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
it("all ten style/mode palettes keep normal text and controls legible", () => {
  const css = readFileSync("src/styles/workspace-themes.css", "utf8");
  for (const style of WORKSPACE_STYLES) {
    for (const mode of [":not(.dark)", ".dark"]) {
      const selector = `html[data-workspace-style="${style.id}"]${mode}`;
      expect(css.includes(selector)).toBe(true);
      const block = css.split(selector)[1]!.split("}")[0]!;
      const token = (name: string) =>
        new RegExp(`--${name}: (#[a-fA-F0-9]{6});`).exec(block)![1]!;
      for (const [fg, bg] of [
        ["foreground", "background"],
        ["muted-foreground", "muted"],
        ["primary-foreground", "primary"],
        ["sidebar-foreground", "sidebar"],
        ["sidebar-primary", "sidebar-accent"],
      ]) {
        expect(
          contrast(token(fg!), token(bg!)),
          `${selector} ${fg}/${bg}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
      expect(
        contrast(token("ring"), token("background")),
      ).toBeGreaterThanOrEqual(3);
    }
  }
});
