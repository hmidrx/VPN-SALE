import { strict as assert } from "node:assert";
import { execFileSync } from "node:child_process";

import { parseCustomerConfig } from "../config/public-config.ts";

assert.equal(parseCustomerConfig({ NEXT_PUBLIC_TELEGRAM_BOT_USERNAME: "valid_bot" }).botUsername, "valid_bot");
assert.equal(parseCustomerConfig({ NEXT_PUBLIC_TELEGRAM_BOT_USERNAME: "@valid_bot" }).botUsername, "valid_bot");
assert.equal(parseCustomerConfig({ NEXT_PUBLIC_TELEGRAM_BOT_USERNAME: "  valid_bot  " }).botUsername, "valid_bot");
assert.equal(parseCustomerConfig({}).botUsername, null);
assert.throws(
  () => parseCustomerConfig({ NEXT_PUBLIC_TELEGRAM_BOT_USERNAME: "bad" }),
  /Invalid public Telegram bot username/,
);
assert.throws(
  () => parseCustomerConfig({ NODE_ENV: "production", NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM: "true" }),
  /Fake Telegram adapter is not allowed in production builds/,
);
assert.equal(
  parseCustomerConfig({ NEXT_PUBLIC_API_BASE_URL: "https://fallback.example.test", NEXT_PUBLIC_CUSTOMER_API_BASE_URL: "https://customer.example.test" }).apiBaseUrl,
  "https://customer.example.test",
);
assert.equal(parseCustomerConfig({ NEXT_PUBLIC_API_BASE_URL: "https://fallback.example.test" }).apiBaseUrl, "https://fallback.example.test");
assert.equal(parseCustomerConfig({}).appName, "VPN-SALE");

// A fresh process proves the default path captures public values without mutating this test's environment.
const loaded = execFileSync(
  process.execPath,
  ["--experimental-strip-types", "--input-type=module", "--eval", "import { loadCustomerConfig } from './src/config/public-config.ts'; process.stdout.write(JSON.stringify(loadCustomerConfig()));"],
  {
    cwd: new URL("../..", import.meta.url),
    encoding: "utf8",
    env: {
      PATH: process.env.PATH ?? "",
      HOME: process.env.HOME ?? "",
      NEXT_PUBLIC_CUSTOMER_API_BASE_URL: "https://compiled.example.test",
      NEXT_PUBLIC_TELEGRAM_BOT_USERNAME: "compiled_bot",
      NEXT_PUBLIC_CUSTOMER_APP_NAME: "CompiledApp",
    },
  },
);
assert.deepEqual(JSON.parse(loaded), {
  apiBaseUrl: "https://compiled.example.test",
  botUsername: "compiled_bot",
  appName: "CompiledApp",
  fakeTelegramEnabled: false,
});
