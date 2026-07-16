import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const appPath = process.argv[2];
if (!appPath) {
  throw new Error("web app path argument is required");
}
const requiredFiles = [
  "app/layout.tsx",
  "app/page.tsx",
  "next.config.mjs",
  "package.json",
  "tsconfig.json",
];
for (const file of requiredFiles) {
  const path = join(appPath, file);
  if (!existsSync(path)) {
    throw new Error(`Missing required web app file: ${path}`);
  }
}
const layout = readFileSync(join(appPath, "app/layout.tsx"), "utf8");
if (!layout.includes('lang="fa"') || !layout.includes('dir="rtl"')) {
  throw new Error(`${appPath} must declare Persian RTL defaults in the root layout`);
}
const page = readFileSync(join(appPath, "app/page.tsx"), "utf8");
if (!page.includes("@vpnsale/ui") || !page.includes("tokens.color")) {
  throw new Error(`${appPath} must consume shared UI design tokens`);
}
console.log(`${appPath} web app check passed`);
