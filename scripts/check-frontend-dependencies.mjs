import { readFileSync } from "node:fs";

const lock = JSON.parse(readFileSync("package-lock.json", "utf8"));
const rootPackage = JSON.parse(readFileSync("package.json", "utf8"));
const vulnerable = [];
const postcssVersions = new Set();

function lte(a, b) {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const da = pa[i] ?? 0;
    const db = pb[i] ?? 0;
    if (da < db) return true;
    if (da > db) return false;
  }
  return true;
}

for (const [path, entry] of Object.entries(lock.packages ?? {})) {
  if (!path.endsWith("node_modules/postcss")) continue;
  postcssVersions.add(entry.version);
  if (lte(entry.version, "8.5.11")) vulnerable.push(`${path}@${entry.version}`);
}

if (postcssVersions.size === 0) throw new Error("package-lock.json does not resolve postcss");
if (vulnerable.length > 0) throw new Error(`vulnerable postcss remains: ${vulnerable.join(", ")}`);
const postcssOverride = rootPackage.overrides?.postcss;
if (
  typeof postcssOverride !== "string" ||
  postcssVersions.size !== 1 ||
  !postcssVersions.has(postcssOverride)
) {
  throw new Error("root package.json must narrowly override postcss to the locked version");
}

for (const [path, entry] of Object.entries(lock.packages ?? {})) {
  const deps = entry.dependencies ?? {};
  const next = deps.next;
  if (typeof next === "string" && /(preview|beta|rc)/i.test(next)) {
    throw new Error(`unstable Next.js dependency marker introduced at ${path}: ${next}`);
  }
}

console.log(`postcss dependency check passed: ${[...postcssVersions].sort().join(", ")}`);
