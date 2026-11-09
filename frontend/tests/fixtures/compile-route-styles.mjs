import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import tailwind from "@tailwindcss/postcss";
import postcss from "postcss";

const result = {};
for (const name of ["globals", "rich-html"]) {
  const from = resolve("src/styles", `${name}.css`);
  const compiled = await postcss([
    tailwind({ base: process.cwd(), optimize: true }),
  ]).process(await readFile(from, "utf8"), { from });
  result[name] = compiled.css;
}
process.stdout.write(JSON.stringify(result));
