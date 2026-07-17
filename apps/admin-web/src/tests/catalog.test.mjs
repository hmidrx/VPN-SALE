import { readFileSync } from "node:fs";
const files = ["../catalog/api.ts","../catalog/format.ts","../catalog/policy.ts","../catalog/editors.tsx","../i18n/catalog.ts","../../app/catalog/page.tsx"].map((p)=>readFileSync(new URL(p, import.meta.url), "utf8")).join("\n");
for (const needle of ["/api/v1/admin/catalog", "refreshOnce", "x-csrf-token", "catalogKeys", "catalog.read", "pricing.manage", "quotes.read", "formatRial", "formatTomanFromRial", "toBytes", "durationLabel", "hasTierOverlap", "MIN_DURATION_FOR_LOCATION", "UNAVAILABLE_LOCATION_QUALITY", "subscription_link", "server pricing engine", "localStorage"]){
  if (needle === "localStorage") { if (files.includes(needle) || files.includes("sessionStorage")) throw new Error("catalog drafts must not persist sensitive data"); continue; }
  if (!files.includes(needle)) throw new Error(`missing ${needle}`);
}
const routeFiles = ["../../app/catalog/categories/page.tsx","../../app/catalog/categories/new/page.tsx","../../app/catalog/products/page.tsx","../../app/catalog/products/new/page.tsx","../../app/catalog/price-lists/page.tsx","../../app/catalog/states/unauthorized/page.tsx"].map((p)=>readFileSync(new URL(p, import.meta.url), "utf8")).join("\n");
for (const needle of ["دسته", "محصول", "FIXED_PLAN", "CUSTOM_PLAN", "فهرست", "۴۰۳"]) if (!routeFiles.includes(needle)) throw new Error(`missing route behavior ${needle}`);
if (/console\.log\([^)]*(token|response|csrf)|provider credential|inbound identifier|panel URL|server IP/i.test(files)) throw new Error("catalog UI must not log secrets or expose provider fields");
