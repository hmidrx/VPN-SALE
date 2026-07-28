import { assertSafeRial, formatTomanFromRial, parseTomanInput, tomanToExactRial } from "../wallet/format";
export { assertSafeRial, formatTomanFromRial, parseTomanInput, tomanToExactRial };
export function statusLabel(status: string): string { return ({REQUIRES_CUSTOMER_ACTION:"آماده پرداخت",REQUIRES_VERIFICATION:"در حال بررسی",PROCESSING:"در حال بررسی",SUCCEEDED:"موفق",FAILED:"ناموفق",CANCELLED:"لغوشده",EXPIRED:"منقضی",RECONCILIATION_REQUIRED:"نیازمند بررسی بیشتر"} as Record<string,string>)[status] ?? "در حال بررسی"; }
export function purposeLabel(p?: string): string { return p === "ORDER_PAYMENT" ? "پرداخت سفارش" : "افزایش موجودی"; }
