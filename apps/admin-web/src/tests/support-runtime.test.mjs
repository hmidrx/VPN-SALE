import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../support/SupportConsole.tsx", import.meta.url), "utf8");
const sla = readFileSync(new URL("../support/SupportSlaInbox.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../support/api.ts", import.meta.url), "utf8");
const types = readFileSync(new URL("../support/types.ts", import.meta.url), "utf8");
const css = readFileSync(new URL("../support/SupportConsole.module.css", import.meta.url), "utf8");
const slaCss = readFileSync(new URL("../support/SupportSlaInbox.module.css", import.meta.url), "utf8");
const page = readFileSync(new URL("../../app/support/page.tsx", import.meta.url), "utf8");
const combined = `${source}\n${sla}\n${api}\n${types}\n${css}\n${slaCss}\n${page}`;

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
  "legalTransitions",
  "replyKey",
  "noteKey",
  "detail.version,\n        replyKey,",
  "detail.version,\n        noteKey,",
  "SupportConsole.module.css",
  "support-runtime-layout",
  "@media (max-width: 700px)",
  "کنسول پشتیبانی",
  "SupportSlaInbox",
  "listOpenSlaEscalations",
  "acknowledgeSupportSlaEscalation",
  "/sla/escalations",
  "SupportSlaInbox.module.css",
  "هشدارهای SLA",
  "<SupportSlaInbox />",
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
