import { readFileSync } from "node:fs";
const flow = [
  ["../../app/catalog/categories/new/page.tsx", "ایجاد دسته"],
  ["../../app/catalog/products/new/page.tsx", "ایجاد محصول"],
  ["../../app/catalog/products/[productId]/custom-plan/page.tsx", "ویرایش پلن سفارشی"],
  ["../../app/catalog/products/[productId]/options/page.tsx", "ویرایش گزینه‌ها"],
  ["../../app/catalog/products/[productId]/constraints/page.tsx", "ویرایش محدودیت‌ها"],
  ["../../app/catalog/price-lists/[priceListId]/rules/page.tsx", "ویرایش قواعد قیمت"],
  ["../../app/catalog/price-lists/[priceListId]/tiers/page.tsx", "ویرایش پله‌های قیمت"],
  ["../../app/catalog/products/[productId]/fulfillment/page.tsx", "الزامات ایفای سفارش"],
  ["../../app/catalog/products/[productId]/preview/page.tsx", "پیش‌نمایش اداری قیمت"],
  ["../../app/catalog/products/[productId]/publication/page.tsx", "بازبینی انتشار"],
  ["../../app/catalog/products/[productId]/versions/page.tsx", "فقط خواندنی"]
];
for (const [path, expected] of flow) {
  const body = readFileSync(new URL(path, import.meta.url), "utf8");
  if (!body.includes(expected)) throw new Error(`catalog e2e route missing ${expected}`);
}
const all = flow.map(([path])=>readFileSync(new URL(path, import.meta.url), "utf8")).join("\n");
for (const forbidden of ["server IP", "panel URL", "inbound identifier", "localStorage", "sessionStorage"]) if (all.includes(forbidden)) throw new Error(`out-of-scope or sensitive term found: ${forbidden}`);
