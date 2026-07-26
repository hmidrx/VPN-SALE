import assert from "node:assert/strict";import fs from "node:fs";
const source=fs.readFileSync(new URL("../src/index.ts",import.meta.url),"utf8");
