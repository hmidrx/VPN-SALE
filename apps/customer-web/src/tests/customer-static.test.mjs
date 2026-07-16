import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const root = new URL("../", import.meta.url);
function source(path) { return readFileSync(new URL(path, root), "utf8"); }
assert.match(source("telegram/adapter.ts"), /initData\?/) ;
assert.doesNotMatch(source("telegram/adapter.ts"), /initDataUnsafe/);
assert.doesNotMatch(source("auth/token-store.ts"), /localStorage|sessionStorage|indexedDB|cookie/i);
assert.match(source("auth/api-client.ts"), /credentials: "include"/);
assert.match(source("auth/api-client.ts"), /authorization/);
assert.match(source("auth/api-client.ts"), /refreshInFlight \?\?=/);
assert.match(source("auth/api-client.ts"), /retry && path !== "\/refresh"/);
assert.match(source("auth/bootstrap.ts"), /bootstrapPromise/);
assert.match(source("auth/state-machine.ts"), /INITIALIZING/);
assert.match(source("auth/state-machine.ts"), /RATE_LIMITED/);
assert.match(source("components/CustomerApp.tsx"), /dir=\{ltr \? "ltr"/);
assert.match(source("components/CustomerApp.tsx"), /--safe-bottom/);
assert.match(source("components/CustomerApp.tsx"), /fa\.states\.browser/);
assert.doesNotMatch(source("components/CustomerApp.tsx"), /wallet|ledger|payment|subscription|invoice/i);
