import { describe, expect, it } from "@rstest/core";
import type { PageMapItem } from "nextra";

import {
  isDocsLanguage,
  isDocsPath,
  localizeDocsPageMap,
} from "@/components/docs/page-map";

const input = [
  {
    data: {
      index: "Overview",
      introduction: "Introduction",
      blog: { type: "page" },
      workspace: { type: "page" },
    },
  },
  { name: "index", route: "/en" },
  {
    name: "introduction",
    route: "/en/introduction",
    children: [
      { name: "core-concepts", route: "/en/introduction/core-concepts" },
    ],
  },
  { name: "blog", route: "/en/blog", children: [] },
  { name: "workspace", route: "/en/workspace" },
] as PageMapItem[];

describe("localized documentation page map", () => {
  it("prefixes documentation routes, including nested pages and the index", () => {
    const result = localizeDocsPageMap(input, "en");
    expect(result).toEqual([
      { data: { index: "Overview", introduction: "Introduction" } },
      { name: "index", route: "/en/docs" },
      {
        name: "introduction",
        route: "/en/docs/introduction",
        children: [
          {
            name: "core-concepts",
            route: "/en/docs/introduction/core-concepts",
          },
        ],
      },
    ]);
    expect(input[1]).toMatchObject({ route: "/en" });
  });

  it("keeps Chinese routes Chinese without double-prefixing", () => {
    const pages = [{ name: "index", route: "/zh/docs" }] as PageMapItem[];
    expect(localizeDocsPageMap(pages, "zh")).toEqual(pages);
    expect(
      localizeDocsPageMap(
        [{ name: "index", route: "/zh" }] as PageMapItem[],
        "zh",
      ),
    ).toEqual(pages);
  });
});

describe("documentation route boundaries", () => {
  it("limits documentation to supported languages and content sections", () => {
    expect(isDocsLanguage("en")).toBe(true);
    expect(isDocsLanguage("zh")).toBe(true);
    expect(isDocsLanguage("ja")).toBe(false);
    expect(isDocsPath([])).toBe(true);
    expect(isDocsPath(["reference", "configuration"])).toBe(true);
    expect(isDocsPath(["workspace"])).toBe(false);
    expect(isDocsPath(["blog"])).toBe(false);
  });
});
