import { existsSync } from "node:fs";
import { join } from "node:path";

const packagePath = process.argv[2];
if (!packagePath) {
  throw new Error("package path argument is required");
}
for (const required of ["package.json", "tsconfig.json"]) {
  const path = join(packagePath, required);
  if (!existsSync(path)) {
    throw new Error(`Missing required package file: ${path}`);
  }
}
console.log(`${packagePath} package check passed`);
