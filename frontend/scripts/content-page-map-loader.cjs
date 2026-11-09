// Nextra's generated navigation map imports every App page as a namespace.
// These pages are not documentation sources; evaluating them registers their
// client references before our existing docs/blog filters can discard them.
// Keep the map topology but give those entries empty metadata, without loading
// any App runtime. Content MDX metadata and _meta modules are left byte-for-byte.
const ts = require("typescript");

function isolateContentPageMap(source) {
  const failure = () => {
    throw new Error("Unsupported content page-map generator output");
  };
  if (
    typeof source !== "string" ||
    !source.includes("export const pageMap = normalizePageMap(") ||
    !source.includes("export const RouteToFilepath =")
  )
    failure();
  const file = ts.createSourceFile(
    "page-map.js",
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.JS,
  );
  if (file.parseDiagnostics.length > 0) failure();
  const replacements = [];
  const accepted = new Set();
  for (const statement of file.statements) {
    if (
      !ts.isImportDeclaration(statement) ||
      !ts.isStringLiteral(statement.moduleSpecifier)
    )
      continue;
    const specifier = statement.moduleSpecifier.text;
    if (!/^private-next-root-dir\/(?:src\/)?app\//.test(specifier)) continue;
    const binding = statement.importClause?.namedBindings;
    if (
      !ts.isNamespaceImport(binding ?? {}) ||
      statement.importClause.name ||
      statement.importClause.isTypeOnly ||
      !/\/page\.[jt]sx?$/.test(specifier) ||
      specifier.split("/").some((part) => part === "." || part === "..") ||
      /[\\?#]/.test(specifier)
    )
      failure();
    accepted.add(statement.moduleSpecifier);
    replacements.push({
      start: statement.getStart(file),
      end: statement.end,
      text: `const ${binding.name.text} = {};`,
    });
  }
  // Fail closed if a Nextra upgrade emits an unrecognized App import/re-export.
  function check(node) {
    if (
      ts.isStringLiteralLike(node) &&
      /^private-next-root-dir\/(?:src\/)?app\//.test(node.text) &&
      !accepted.has(node)
    )
      failure();
    ts.forEachChild(node, check);
  }
  check(file);
  let result = source;
  for (const { start, end, text } of replacements.reverse())
    result = result.slice(0, start) + text + result.slice(end);
  return result;
}

module.exports = function contentPageMapLoader(source) {
  return isolateContentPageMap(source);
};
module.exports.isolateContentPageMap = isolateContentPageMap;
