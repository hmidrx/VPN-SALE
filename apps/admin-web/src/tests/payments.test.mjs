import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
const src = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

function readProjectFile(path) {
  return readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
}
function assertFileContains(path, needle) {
  if (!readProjectFile(path).includes(needle))
    throw new Error(`missing ${needle} in ${path}`);
}
function assertFileNotContains(path, needle) {
  if (readProjectFile(path).includes(needle))
    throw new Error(`forbidden ${needle} in ${path}`);
}
const files = [
  "../payments/api.ts",
  "../payments/types.ts",
  "../payments/format.ts",
  "../payments/validation.ts",
  "../payments/policy.ts",
  "../payments/components.tsx",
  "../components/PaymentOpsShell.tsx",
  "../i18n/payments.ts",
]
  .map(src)
  .join("\n");
for (const needle of [
  "payment_methods.read",
  "payment_methods.manage",
  "payments.read",
  "payment_webhooks.read",
  "payment_webhooks.retry",
  "audit.read",
  "security_events.read",
  "ledger.read",
  'cache: "no-store"',
  "x-csrf-token",
  "refreshOnce",
  "Retry-After",
  "formatRial",
  "formatToman",
  "secretKeyPattern",
  "validatePage",
  "validateMethodAmounts",
])
  if (!files.includes(needle))
    throw new Error(`missing payment invariant ${needle}`);
if (
  /localStorage|sessionStorage|IndexedDB|console\.log\(|mark paid|force success|create settlement|raw-body viewer|api key|merchant-secret/i.test(
    files,
  )
)
  throw new Error("forbidden payment persistence or unsafe control in modules");
const appRoot = new URL("../../app/management", import.meta.url).pathname;
function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
const pages =
  walk(appRoot)
    .filter(
      (p) =>
        p.endsWith("page.tsx") &&
        /payment(s|-methods|-intents|-attempts|-settlements|-webhooks)/.test(p),
    )
    .map((p) => readFileSync(p, "utf8"))
    .join("\n") + files;
for (const needle of [
  "نمای کلی عملیات پرداخت",
  "روش‌های پرداخت",
  "ایجاد draft روش پرداخت",
  "جزئیات و lifecycle روش پرداخت",
  "کشف نیت‌های پرداخت",
  "جزئیات immutable نیت پرداخت",
  "جزئیات attempt و verification",
  "جزئیات settlement read-only",
  "صندوق وبهوک پرداخت",
  "جزئیات sanitized وبهوک",
])
  if (!pages.includes(needle)) throw new Error(`missing route page ${needle}`);
for (const needle of [
  "Cursor pagination",
  "Credential",
  "Adapter capabilities",
  "activate",
  "pause",
  "maintenance",
  "retire",
  "immutable",
  "amount mismatch",
  "currency mismatch",
  "dead-letter",
  "invalid-signature",
  "Retry-After",
  "audit.read",
  "security_events.read",
  "۴۰۳",
  "سرویس پرداخت در دسترس نیست",
  "خطای امن پرداخت",
  "رکورد یافت نشد",
  "ریال",
  "تومان",
  "raw body",
  "signature",
])
  if (!pages.includes(needle)) throw new Error(`missing UX coverage ${needle}`);
for (const forbidden of [
  "mark-paid",
  "force-success",
  "settlement-create",
  "refund-management",
  "reconciliation-repair",
  "unrestricted raw json editor",
  "raw-signature-control",
  "raw-provider-response-control",
])
  if (pages.includes(forbidden))
    throw new Error(`forbidden UI term ${forbidden}`);
const docs = src("../../../../docs/milestones/MILESTONE_4_A2B1_PLAN.md");
for (const needle of [
  "Route inventory",
  "Permissions",
  "Payment-method lifecycle",
  "Payment-state terminology",
  "Webhook processing",
  "Credential boundaries",
  "Security controls",
  "Storage policy",
  "Non-goals",
  "Acceptance criteria",
])
  if (!docs.includes(needle))
    throw new Error(`missing plan coverage ${needle}`);

// Milestone 4-A2B2 static recovery workflow guards.
assertFileContains("src/payments/api.ts", "/refunds");
assertFileContains("src/payments/api.ts", "/reconciliation/dry-run");
assertFileContains("src/payments/api.ts", "/late-settlements");
assertFileContains("src/payments/api.ts", "/unapplied-payments");
assertFileContains("src/payments/api.ts", "/recover");
assertFileContains("app/management/payment-refunds/page.tsx", "تأیید دو نفره");
assertFileContains(
  "app/management/payment-reconciliation/page.tsx",
  "مغایرت بحرانی مسدود است",
);
assertFileNotContains(
  "app/management/payment-webhook-recovery/page.tsx",
  "localStorage",
);
