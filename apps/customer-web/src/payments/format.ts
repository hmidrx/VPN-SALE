import { assertSafeRial, formatRial, formatTomanFromRial } from "../wallet/format";
export { assertSafeRial, formatRial, formatTomanFromRial };
export function parseRialInput(raw: string): number { const v = raw.trim().replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))); if (!/^[0-9]+$/.test(v)) throw new Error("amount_integer_rial_required"); const n = Number(v); return assertSafeRial(n, "amount_rial"); }
export function statusLabel(status: string): string { return ({REQUIRES_CUSTOMER_ACTION:"نیازمند انتقال به درگاه",REQUIRES_VERIFICATION:"در انتظار راستی‌آزمایی",PROCESSING:"در حال پردازش",SUCCEEDED:"موفق",FAILED:"ناموفق",CANCELLED:"لغوشده",EXPIRED:"منقضی",RECONCILIATION_REQUIRED:"نیازمند بررسی مالی"} as Record<string,string>)[status] ?? "وضعیت پرداخت"; }
export function purposeLabel(p?: string): string { return p === "ORDER_PAYMENT" ? "پرداخت سفارش" : "شارژ کیف پول"; }
