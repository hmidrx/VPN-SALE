import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../../.next/server/app/index.html", import.meta.url), "utf8");
const bridge = "https://telegram.org/js/telegram-web-app.js?63";
const bridgeBootstrap = `(self.__next_s=self.__next_s||[]).push([\"${bridge}\",{}])`;
const bridgeIndex = html.indexOf(bridgeBootstrap);
const applicationBootstrapIndex = html.indexOf("self.__next_f.push");

assert.notEqual(bridgeIndex, -1, "customer production HTML does not initialize the official Telegram Mini App bridge");
assert.equal(html.split(bridgeBootstrap).length - 1, 1, "official Telegram Mini App bridge is duplicated");
assert.ok(applicationBootstrapIndex === -1 || bridgeIndex < applicationBootstrapIndex, "Telegram bridge must precede Next.js application script execution");
for (const forbidden of ["POSTGRES_PASSWORD=", "DATABASE_URL=", "VPN_SALE_TELEGRAM_BOT_TOKEN="]) {
  assert.doesNotMatch(html, new RegExp(forbidden), `customer HTML contains forbidden runtime secret marker: ${forbidden}`);
}
