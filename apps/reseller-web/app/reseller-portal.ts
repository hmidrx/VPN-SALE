export type ResellerStatus = "ACTIVE" | "SUSPENDED" | "BLOCKED" | "TERMINATED";
export type ValidationResult = { ok: true } | { ok: false; reason: string };

type NavigationItem = { href: string; label: string };
type CatalogProduct = {
  id: string;
  name: string;
  description: string;
  version: string;
  durationDays: number;
  trafficGb: number;
  deviceLimit: number;
  wholesaleRial: number;
  minRetailRial: number;
  maxRetailRial: number;
  available: boolean;
};
type PortalSnapshot = {
  account: { status: ResellerStatus; tier: string };
  wallet: { availableRial: number; reservedRial: number };
  credit: { availableRial: number; utilizedRial: number };
  customers: { usedQuota: number; maxQuota: number };
  orders: { pendingCount: number };
  catalog: CatalogProduct[];
  quoteFlow: string[];
  customerRows: Array<{ reference: string; label: string; state: string; invitation: string }>;
  orderRows: Array<{ reference: string; customerLabel: string; wholesaleRial: number; fulfillmentState: "READY_FOR_FULFILLMENT" }>;
  remark: { template: string; allowedPlaceholders: string[] };
  brandingDraft: BrandingDraft;
  activity: Array<{ reference: string; label: string }>;
};
export type BrandingDraft = {
  displayBrand: string;
  shortName: string;
  accentColor: string;
  supportUrl: string;
  footerText: string;
};

export const resellerNavigation: NavigationItem[] = [
  { href: "#dashboard", label: "داشبورد" },
  { href: "#catalog", label: "کاتالوگ" },
  { href: "#customers", label: "مشتریان" },
  { href: "#new-order", label: "سفارش جدید" },
  { href: "#orders", label: "سفارش‌ها" },
  { href: "#wallet", label: "کیف پول و اعتبار" },
  { href: "#catalog", label: "قیمت‌گذاری" },
  { href: "#remarks", label: "Remark" },
  { href: "#brand", label: "برند" },
  { href: "#security", label: "فعالیت" },
  { href: "#security", label: "پروفایل و امنیت" },
];

export const storagePolicyChecklist = [
  "access token، refresh token، CSRF و Telegram initData در حافظه مرورگر پایدار ذخیره نمی‌شوند.",
  "داده مالی، مشتری، quote، order، remark و branding در localStorage، sessionStorage یا IndexedDB نوشته نمی‌شود.",
  "کلید idempotency لاگ یا persist نمی‌شود و retry مبهم به همان عملیات امن متصل می‌ماند.",
  "فیلترهای امن لیست می‌توانند در URL باشند، اما پاسخ کامل API هرگز در URL یا storage قرار نمی‌گیرد.",
];

export const demoResellerPortal: PortalSnapshot = {
  account: { status: "ACTIVE", tier: "GOLD" },
  wallet: { availableRial: 24_000_000, reservedRial: 2_000_000 },
  credit: { availableRial: 15_000_000, utilizedRial: 5_000_000 },
  customers: { usedQuota: 18, maxQuota: 50 },
  orders: { pendingCount: 3 },
  catalog: [
    { id: "prod-managed-30", name: "اشتراک مدیریت‌شده ۳۰ روزه", description: "نمونه نمایشی از snapshot محصول بدون سرور یا provider", version: "pv-2026-07", durationDays: 30, trafficGb: 80, deviceLimit: 2, wholesaleRial: 4_200_000, minRetailRial: 4_800_000, maxRetailRial: 7_500_000, available: true },
    { id: "prod-managed-90", name: "اشتراک مدیریت‌شده ۹۰ روزه", description: "قابل سفارش فقط با eligibility backend", version: "pv-2026-07", durationDays: 90, trafficGb: 240, deviceLimit: 3, wholesaleRial: 11_500_000, minRetailRial: 13_000_000, maxRetailRial: 19_000_000, available: true },
  ],
  quoteFlow: [
    "انتخاب مشتری مدیریت‌شده و محصول مجاز از API صفحه‌بندی‌شده.",
    "دریافت قیمت مؤثر، بازه retail و pricing explanation از backend.",
    "ثبت label و remark امن بدون تغییر credential، UUID، Host، SNI، Path یا protocol.",
    "ایجاد quote immutable با pricing version و expiration.",
    "checkout با PREPAID یا CREDIT و refresh نتیجه مالی معتبر.",
  ],
  customerRows: [
    { reference: "cus_res_8K2P", label: "مشتری سازمانی شرق", state: "LINKED", invitation: "ACCEPTED" },
    { reference: "cus_res_4N7Q", label: "فروشگاه همکار", state: "PENDING", invitation: "SENT" },
  ],
  orderRows: [
    { reference: "ord_res_M5D_001", customerLabel: "مشتری سازمانی شرق", wholesaleRial: 4_200_000, fulfillmentState: "READY_FOR_FULFILLMENT" },
  ],
  remark: { template: "{reseller_brand}-{customer_label}-{product_name}-{sequence}", allowedPlaceholders: ["{reseller_brand}", "{customer_label}", "{product_name}", "{location}", "{order_short_id}", "{service_short_id}", "{sequence}"] },
  brandingDraft: { displayBrand: "نمایندگی امن پارس", shortName: "پارس", accentColor: "#2454ff", supportUrl: "https://support.example.invalid/reseller", footerText: "ارائه توسط VPN-SALE با هویت امنیتی پلتفرم" },
  activity: [
    { reference: "act_1001", label: "quote ایجاد شد و pricing snapshot ذخیره شد." },
    { reference: "act_1002", label: "checkout پیش‌پرداخت یک debit دفترکل ایجاد کرد." },
    { reference: "act_1003", label: "پیش‌نویس برند اعتبارسنجی و آماده انتشار شد." },
  ],
};

export function formatRial(amount: number): string {
  assertIntegerRial(amount);
  return `${new Intl.NumberFormat("fa-IR").format(amount)} ریال`;
}

export function formatTomanPresentation(amount: number): string {
  assertIntegerRial(amount);
  return `${new Intl.NumberFormat("fa-IR").format(Math.trunc(amount / 10))} تومان نمایشی`;
}

export function validateRemarkTemplate(template: string): ValidationResult {
  const allowed = new Set(demoResellerPortal.remark.allowedPlaceholders);
  if (template.length < 3 || template.length > 96) return { ok: false, reason: "طول remark مجاز نیست." };
  if(/[\u0000-\u001F<>]|script|https?:|data:/iu.test(template)) return { ok: false, reason: "remark شامل نویسه، اسکریپت یا URL ناامن است." };
  const placeholders = template.match(/\{[a-z_]+\}/giu) ?? [];
  for (const placeholder of placeholders) if (!allowed.has(placeholder)) return { ok: false, reason: `placeholder ناشناخته است: ${placeholder}` };
  return { ok: true };
}

export function validateBrandingDraft(draft: BrandingDraft): ValidationResult {
  if (!/^#[0-9a-f]{6}$/iu.test(draft.accentColor)) return { ok: false, reason: "رنگ accent باید token معتبر hex باشد." };
  if(/[<>]|script|javascript:|data:/iu.test(`${draft.displayBrand} ${draft.shortName} ${draft.footerText}`)) return { ok: false, reason: "HTML، CSS یا JavaScript دلخواه مجاز نیست." };
  if (!draft.supportUrl.startsWith("https://") || draft.supportUrl.includes("@")) return { ok: false, reason: "نشانی پشتیبانی باید HTTPS و بدون credential باشد." };
  return { ok: true };
}

function assertIntegerRial(amount: number): void {
  if (!Number.isSafeInteger(amount) || amount < 0) throw new Error("money must be a non-negative integer rial amount");
}
