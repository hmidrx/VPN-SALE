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
if ((!page.includes("@vpnsale/ui") || !page.includes("tokens.color")) && !layout.includes('import "@vpnsale/ui/theme.css"')) {
  throw new Error(`${appPath} must consume shared UI design tokens`);
}
const tsconfig = JSON.parse(readFileSync(join(appPath, "tsconfig.json"), "utf8"));
const paths = tsconfig.compilerOptions?.paths ?? {};
if (paths["@vpnsale/ui"]?.[0] !== "../../packages/ui/src/index.ts") {
  throw new Error(`${appPath} must resolve @vpnsale/ui relative to the app for Next.js builds`);
}
if (paths["@vpnsale/shared-typescript"]?.[0] !== "../../packages/shared-typescript/src/api-client.ts") {
  throw new Error(`${appPath} must resolve @vpnsale/shared-typescript relative to the app for Next.js builds`);
}
console.log(`${appPath} web app check passed`);
