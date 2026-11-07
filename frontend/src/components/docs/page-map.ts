import type { PageMapItem } from "nextra";

export const DOC_LANGUAGES = ["en", "zh"] as const;
export type DocsLanguage = (typeof DOC_LANGUAGES)[number];
const DOC_SECTIONS = new Set([
  "index",
  "introduction",
  "harness",
  "application",
  "tutorials",
  "reference",
]);

export function isDocsLanguage(value: string): value is DocsLanguage {
  return DOC_LANGUAGES.includes(value as DocsLanguage);
}

export function isDocsPath(path: string[]): boolean {
  return path.length === 0 || DOC_SECTIONS.has(path[0]!);
}

/** Content lives at /<lang>; only documentation is exposed at /<lang>/docs. */
export function localizeDocsPageMap(
  items: PageMapItem[],
  lang: DocsLanguage,
): PageMapItem[] {
  const localize = (item: PageMapItem): PageMapItem => {
    if ("data" in item) return item;
    const prefix = `/${lang}`;
    const docsPrefix = `${prefix}/docs`;
    const route =
      item.route === prefix
        ? docsPrefix
        : item.route.startsWith(`${prefix}/`) &&
            item.route !== docsPrefix &&
            !item.route.startsWith(`${docsPrefix}/`)
          ? `${docsPrefix}${item.route.slice(prefix.length)}`
          : item.route;
    return {
      ...item,
      route,
      ...("children" in item ? { children: item.children.map(localize) } : {}),
    };
  };
  return items.flatMap((item): PageMapItem[] => {
    if ("data" in item) {
      return [
        {
          ...item,
          data: Object.fromEntries(
            Object.entries(item.data).filter(([name]) =>
              DOC_SECTIONS.has(name),
            ),
          ),
        },
      ];
    }
    return DOC_SECTIONS.has(item.name) ? [localize(item)] : [];
  });
}
