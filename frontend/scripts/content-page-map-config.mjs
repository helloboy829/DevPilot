import { fileURLToPath } from "node:url";

const loader = fileURLToPath(
  new URL("./content-page-map-loader.cjs", import.meta.url),
);
const placeholder =
  /(?:^|[/\\])nextra[/\\]dist[/\\]server[/\\]page-map[/\\]placeholder\.js$/;

/** Apply only to Nextra's generated page-map module, never to App routes. */
export function withContentPageMapIsolation(config) {
  const rules = config.turbopack?.rules;
  const keys = Object.keys(rules ?? {}).filter((key) => placeholder.test(key));
  if (keys.length !== 1 || !Array.isArray(rules[keys[0]].loaders)) {
    throw new Error("Unsupported Nextra page-map build configuration");
  }
  const key = keys[0];
  const webpack = config.webpack;
  return {
    ...config,
    turbopack: {
      ...config.turbopack,
      rules: {
        ...rules,
        // Both loader runners execute right-to-left: Nextra first, projection last.
        [key]: { ...rules[key], loaders: [loader, ...rules[key].loaders] },
      },
    },
    webpack(buildConfig, options) {
      const result = webpack ? webpack(buildConfig, options) : buildConfig;
      result.module ??= {};
      result.module.rules ??= [];
      result.module.rules.push({
        test: placeholder,
        enforce: "post",
        use: [loader],
      });
      return result;
    },
  };
}
