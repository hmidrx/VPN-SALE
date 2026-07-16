import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const root = process.argv[2] ?? ".";
const forbidden = [/\.only\(/, /console\.log\(/, /any\s*;/];
const files = [];
function walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (["node_modules", ".next"].includes(entry)) continue;
    const path = join(dir, entry);
    const stat = statSync(path);
    if (stat.isDirectory()) walk(path);
    else if (!entry.endsWith(".d.ts") && /\.(ts|tsx|js|mjs)$/.test(entry)) files.push(path);
  }
}
walk(root);
for (const file of files) {
  const content = readFileSync(file, "utf8");
  for (const pattern of forbidden) {
    if (pattern.test(content)) {
      throw new Error(`${file} violates lint pattern ${pattern}`);
    }
  }
}
if (files.length === 0) {
  throw new Error(`${root} has no lintable source files`);
}
console.log(`${root} linted ${files.length} files`);
