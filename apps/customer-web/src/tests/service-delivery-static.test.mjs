import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root = new URL("../", import.meta.url);
const source = (path) => readFileSync(new URL(path, root), "utf8");
const api = source("services.ts");
const connection = source("components/ServiceConnection.tsx");
const services = source("components/Services.tsx");

assert.match(api, /\/api\/v1\/customer\/delivery\/services/);
assert.match(api, /\/api\/v1\/customer\/delivery\/qr/);
assert.match(api, /credentials: "include"/);
assert.match(api, /cache: "no-store"/);
assert.match(api, /subscriptionPathPattern/);
assert.doesNotMatch(api, /localStorage|sessionStorage|indexedDB|initDataUnsafe/i);

assert.match(connection, /نمایش کانفیگ مستقیم/);
assert.match(connection, /دریافت لینک اشتراک/);
assert.match(connection, /تأیید ساخت لینک جدید/);
assert.match(connection, /تأیید لغو اشتراک/);
assert.match(connection, /ambiguousMutation/);
assert.doesNotMatch(connection, /localStorage|sessionStorage|indexedDB|document\.cookie/i);
assert.doesNotMatch(connection, /console\.(?:log|info|debug|warn|error)/);

const effects = [...connection.matchAll(/React\.useEffect\(([\s\S]*?)\n\s*\);/g)];
for (const effect of effects) {
  assert.doesNotMatch(
    effect[1],
    /getServiceDelivery|issueServiceSubscription|rotateServiceSubscription|revokeServiceSubscription|getConnectionQr/,
  );
}

assert.match(services, /ServiceConnectionPanel/);
assert.doesNotMatch(
  services,
  /فرمت‌های تحویل معتبر پس از دریافت امن از سرور اینجا نمایش داده می‌شوند/,
);
