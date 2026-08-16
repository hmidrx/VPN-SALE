import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../support/SupportConsole.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../support/api.ts", import.meta.url), "utf8");
const types = readFileSync(new URL("../support/types.ts", import.meta.url), "utf8");
const combined = `${source}\n${api}\n${types}`;

for (const value of [
  "/api/v1/admin/support-runtime",
  "listSupportConversations",
  "claimSupportConversation",
  "replySupportConversation",
  "addSupportInternalNote",
  "changeSupportStatus",
  "expected_version",
  "Idempotency-Key",
  "internal-notes",
  "کنسول پشتیبانی",
]) {
  if (!combined.includes(value)) throw new Error(`missing ${value}`);
}

for (const forbidden of [
  "CONVERSATIONS: dict",
  "localStorage.setItem",
  "sessionStorage.setItem",
  "requester_user_id",
  "assigned_agent_id",
]) {
  if (combined.includes(forbidden)) throw new Error(`unsafe or internal ${forbidden}`);
}
