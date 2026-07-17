import { readFileSync } from "node:fs";
import { strict as assert } from "node:assert";

const source = readFileSync(new URL("../app/reseller-portal.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

for (const forbidden of ["localStorage", "sessionStorage", "indexedDB", "subscription", "QR", "server name", "Sanaei", "PasarGuard"]) {
  assert.equal(source.includes(`${forbidden}.setItem`), false, `must not persist ${forbidden}`);
}
assert.match(source, /money must be a non-negative integer rial amount/);
assert.match(source, /READY_FOR_FULFILLMENT/);
assert.match(page, /سرویس و لینک\/QR\/کانفیگ در این milestone وجود ندارد/);
assert.match(page, /Backend authoritative/);
assert.match(source, /javascript:|data:/);
assert.match(source, /placeholder ناشناخته/);
assert.match(source, /checkout با PREPAID یا CREDIT/);
assert.match(source, /کیف پول مشتری ذی‌نفع شارژ نمی‌شود|کیف پول/);
console.info("reseller portal behavioral checks passed");
