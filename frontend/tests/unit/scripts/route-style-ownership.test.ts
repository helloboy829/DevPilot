import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import frozenSafelist from "../../fixtures/rich-html-safelist.json";

const readStyle = (name: string) =>
  readFileSync(resolve("src/styles", name), "utf8");

describe("route CSS ownership", () => {
  it("preserves every historical dynamic HTML safelist directive", () => {
    expect(
      readStyle("rich-html.css").match(/@source inline\([^\n]+\);/g),
    ).toEqual(frozenSafelist);
    expect(readStyle("globals.css")).not.toContain("@source inline(");
  });
  it("scans all runtime sources and complete installed rendering chunks, not tests or build output", () => {
    const source = readStyle("globals.css");
    expect(source).toContain('@import "tailwindcss" source(none);');
    const runtimeSources = [
      "../",
      "../../public",
      "../../node_modules/streamdown/dist/*.js",
      "../../node_modules/@streamdown/code/dist/*.js",
      "../../node_modules/@streamdown/mermaid/dist/*.js",
    ];
    expect(source.match(/@source "[^"\n]+";/g)).toEqual(
      runtimeSources.map((path) => `@source "${path}";`),
    );
    expect(readStyle("theme-tokens.css")).not.toContain("@source");
    expect(readStyle("rich-html.css")).not.toContain(
      '@reference "./globals.css"',
    );
  });
  it("compiles the full raw HTML palette without another application's preflight or utility scan", () => {
    const result = JSON.parse(
      execFileSync(
        process.execPath,
        ["tests/fixtures/compile-route-styles.mjs"],
        { encoding: "utf8" },
      ),
    ) as Record<"globals" | "rich-html", string>;
    expect(result.globals).not.toContain(".text-stone-950");
    expect(result.globals).not.toContain("text-\\[rgb\\(1\\,35\\,69\\)\\]");
    expect(result.globals).toContain("--sdm-c");
    for (const selector of [
      ".text-stone-950",
      ".px-24",
      ".leading-loose",
      ".text-6xl",
    ])
      expect(result["rich-html"]).toContain(selector);
    expect(result["rich-html"]).toContain("--color-stone-950:");
    expect(result["rich-html"]).not.toContain("box-sizing:border-box");
    expect(result["rich-html"]).not.toContain("data-workspace-style");
    expect(result["rich-html"]).not.toContain("--sdm-c");
    expect(Buffer.byteLength(result["rich-html"])).toBeLessThan(30_000);
  });
});
