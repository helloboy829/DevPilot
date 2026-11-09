import { fileURLToPath } from "node:url";

import { describe, expect, it } from "@rstest/core";

import { withContentPageMapIsolation } from "../../../scripts/content-page-map-config.mjs";
import { isolateContentPageMap } from "../../../scripts/content-page-map-loader.cjs";

const wrap = (imports: string) => `${imports}
export const pageMap = normalizePageMap([{ name: 'workspace', frontMatter: getMetadata(app) }]);
export const RouteToFilepath = { '/en/index': 'src/content/en/index.mdx' };
`;

const content = `import { metadata as mdx } from 'private-next-root-dir/src/content/en/index.mdx?metadata';
import meta from 'private-next-root-dir/src/content/en/_meta.ts';`;

describe("content-only Nextra page-map projection", () => {
  for (const directory of ["app", "src/app"]) {
    for (const extension of ["js", "jsx", "ts", "tsx"]) {
      it(`isolates ${directory} namespace pages (${extension}) without touching content`, () => {
        const source = wrap(`${content}
import * as app from 'private-next-root-dir/${directory}/workspace/operations/page.${extension}';`);
        const result = isolateContentPageMap(source);
        expect(result).toContain(content);
        expect(result).toContain("const app = {};");
        expect(result).not.toContain(`private-next-root-dir/${directory}/`);
        expect(result.slice(result.indexOf("export const pageMap"))).toBe(
          source.slice(source.indexOf("export const pageMap")),
        );
        expect(isolateContentPageMap(result)).toBe(result);
      });
    }
  }
  it("handles comments, double quotes and multiline imports using syntax nodes", () => {
    const source = wrap(`// preserve navigation comment
import * as
 app
 from "private-next-root-dir/src/app/page.tsx";`);
    expect(isolateContentPageMap(source))
      .toContain(`// preserve navigation comment
const app = {};`);
  });
  it("keeps a content-only generator result byte-for-byte", () => {
    const source = wrap(content);
    expect(isolateContentPageMap(source)).toBe(source);
  });
  it("projects multiple App entries without offset corruption", () => {
    const source =
      wrap(`import * as app from 'private-next-root-dir/src/app/page.tsx';
import * as other from 'private-next-root-dir/src/app/login/page.tsx';`);
    const result = isolateContentPageMap(source);
    expect(result).toContain(`const app = {};
const other = {};`);
    expect(result).not.toContain("private-next-root-dir");
  });
  for (const unexpected of [
    "import app from 'private-next-root-dir/src/app/page.tsx';",
    "import { metadata } from 'private-next-root-dir/src/app/page.tsx';",
    "import 'private-next-root-dir/src/app/page.tsx';",
    "export * from 'private-next-root-dir/src/app/page.tsx';",
    "const app = import('private-next-root-dir/src/app/page.tsx');",
    "import * as app from 'private-next-root-dir/src/app/_meta.ts';",
    "import * as app from 'private-next-root-dir/src/app/a/../page.tsx';",
    "import * as app from 'private-next-root-dir/src/app/page.tsx?changed';",
    "import * as app from 'private-next-root-dir/src/app/page.mdx';",
  ]) {
    it(`rejects unsupported App import syntax: ${unexpected.split(" from")[0]}`, () => {
      expect(() => isolateContentPageMap(wrap(unexpected))).toThrow(
        "Unsupported content page-map generator output",
      );
    });
  }
  for (const source of [
    "",
    "export const pageMap = [];",
    wrap("import * as ???"),
  ]) {
    it("rejects missing markers or malformed generator output", () => {
      expect(() => isolateContentPageMap(source)).toThrow(
        "Unsupported content page-map generator output",
      );
    });
  }
});

describe("narrow build wiring", () => {
  const key = "**/nextra/dist/server/page-map/placeholder.js";
  const makeConfig = () => ({
    output: "standalone",
    turbopack: {
      resolveAlias: { KEEP: "existing" },
      rules: {
        [key]: {
          loaders: [
            { loader: "nextra-loader", options: { contentDir: "src/content" } },
          ],
        },
        "*.mdx": { loaders: ["keep-mdx-loader"] },
      },
    },
  });
  it("runs the projection after Nextra without changing other loaders or aliases", () => {
    const original = makeConfig();
    const config = withContentPageMapIsolation(original);
    expect(config.output).toBe("standalone");
    expect(config.turbopack.resolveAlias).toBe(original.turbopack.resolveAlias);
    expect(config.turbopack.rules["*.mdx"]).toBe(
      original.turbopack.rules["*.mdx"],
    );
    expect(config.turbopack.rules[key].loaders[0]).toBe(
      fileURLToPath(
        new URL(
          "../../../scripts/content-page-map-loader.cjs",
          import.meta.url,
        ),
      ),
    );
    expect(config.turbopack.rules[key].loaders.slice(1)).toEqual(
      original.turbopack.rules[key].loaders,
    );
    expect(original.turbopack.rules[key].loaders).toHaveLength(1);
  });
  it("preserves the webpack hook and adds an exact post-loader only", () => {
    let called = false;
    const config = withContentPageMapIsolation({
      ...makeConfig(),
      webpack: (input: { kept: boolean }) => {
        called = true;
        return input;
      },
    });
    const result = config.webpack({ kept: true }, {});
    expect(called).toBe(true);
    expect(result.kept).toBe(true);
    const rule = result.module.rules[0];
    expect(rule.enforce).toBe("post");
    for (const path of [
      "/node_modules/nextra/dist/server/page-map/placeholder.js",
      "C:\\node_modules\\nextra\\dist\\server\\page-map\\placeholder.js",
    ])
      expect(rule.test.test(path)).toBe(true);
    for (const path of [
      "/src/app/workspace/page.tsx",
      "/node_modules/nextra/dist/client/components/index.js",
      "/src/my-nextra/dist/server/page-map/placeholder.js",
    ])
      expect(rule.test.test(path)).toBe(false);
  });
  for (const config of [
    {},
    { turbopack: { rules: {} } },
    { turbopack: { rules: { [key]: {} } } },
  ]) {
    it("fails closed when upstream build shape changes", () => {
      expect(() => withContentPageMapIsolation(config)).toThrow(
        "Unsupported Nextra page-map build configuration",
      );
    });
  }
});
