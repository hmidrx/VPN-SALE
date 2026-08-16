import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const api = fs.readFileSync(new URL("../support/api.ts", import.meta.url), "utf8");
const consoleSource = fs.readFileSync(
  new URL("../support/SupportConsole.tsx", import.meta.url),
  "utf8",
);


test("support agent image client sends raw binary with idempotency and ticket version", () => {
  assert.match(api, /export async function uploadSupportAttachment/);
  assert.match(api, /expected_version/);
  assert.match(api, /Idempotency-Key/);
  assert.match(api, /body: file/);
  assert.match(api, /binaryHeaders\(file\.type, idempotencyKey\)/);
});


test("support console limits and refreshes durable agent image sends", () => {
  assert.match(consoleSource, /image\/jpeg,image\/png,image\/webp/);
  assert.match(consoleSource, /supportImageMaxBytes = 5 \* 1024 \* 1024/);
  assert.match(consoleSource, /uploadSupportAttachment\(/);
  assert.match(consoleSource, /agentImageKey/);
  assert.match(consoleSource, /await openTicket\(detail\.reference, true\)/);
  assert.match(consoleSource, /ارسال تصویر به مشتری/);
});
