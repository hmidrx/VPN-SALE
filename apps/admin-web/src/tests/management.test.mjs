import { readFileSync } from "node:fs";
const files = ["../management/api.ts","../management/permissions.ts","../management/format.ts","../i18n/management.ts"].map((p)=>readFileSync(new URL(p, import.meta.url), "utf8")).join("\n");
for (const needle of ["/api/v1/admin/management", "serializeQuery", "refreshOnce", "x-csrf-token", "retryAfter", "admins.read", "security.manage", "metadataEntries", "SECRET_RE"]) if (!files.includes(needle)) throw new Error(`missing ${needle}`);
if (/localStorage\.setItem|sessionStorage\.setItem|console\.log\([^)]*(response|token|invitation)/.test(files)) throw new Error("management must not persist or log sensitive responses");
const invitePage = readFileSync(new URL("../../app/management/admins/invite/page.tsx", import.meta.url), "utf8");
if (invitePage.includes("localStorage") || invitePage.includes("sessionStorage")) throw new Error("invitation token display must stay ephemeral");
if (!invitePage.includes("useState<string|null>") || !invitePage.includes("setToken(null)")) throw new Error("one-time token memory clearing missing");
const auditDetail = readFileSync(new URL("../../app/management/audit/[eventId]/page.tsx", import.meta.url), "utf8");
if (!auditDetail.includes("metadataEntries")) throw new Error("audit detail must use safe metadata renderer");

const ownerDashboard = readFileSync(new URL("../components/OwnerControlDashboard.tsx", import.meta.url), "utf8");
for (const needle of ["operationsHealth", "هیچ وضعیت ساختگی نمایش داده نمی‌شود", "service_operations", "usage_sync"]) if (!ownerDashboard.includes(needle)) throw new Error(`owner dashboard missing authoritative surface: ${needle}`);
if (!files.includes('operationsHealth: () => request<OperationsHealthSnapshot>("/operations/health")')) throw new Error("owner health must use the authenticated management client");
if (/Math\.random|mock|fake/i.test(ownerDashboard)) throw new Error("owner dashboard must not fabricate operational values");
