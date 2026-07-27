import { strict as assert } from "node:assert";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const appDirectory = fileURLToPath(new URL("../..", import.meta.url));
const outputDirectory = join(appDirectory, ".next");
const publicSentinels = ["buildsentinel_bot", "https://api.example.test", "BuildSentinel"];
const privateSentinels = [
  "private-telegram-token-sentinel",
  "private-postgres-password-sentinel",
  "private-database-url-sentinel",
  "private-session-secret-sentinel",
  "private-encryption-key-sentinel",
  "private-rate-limit-secret-sentinel",
];

function bundleText(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? bundleText(path) : [readFileSync(path).toString("utf8")];
  }).join("\n");
}

rmSync(outputDirectory, { recursive: true, force: true });
try {
  execFileSync("npm", ["run", "build"], {
    cwd: appDirectory,
    stdio: "inherit",
    env: {
      PATH: process.env.PATH ?? "",
      HOME: process.env.HOME ?? "",
      CI: process.env.CI ?? "",
      NEXT_TELEMETRY_DISABLED: "1",
      NODE_ENV: "production",
      NEXT_PUBLIC_TELEGRAM_BOT_USERNAME: publicSentinels[0],
      NEXT_PUBLIC_CUSTOMER_API_BASE_URL: publicSentinels[1],
      NEXT_PUBLIC_API_BASE_URL: publicSentinels[1],
      NEXT_PUBLIC_CUSTOMER_APP_NAME: publicSentinels[2],
      VPN_SALE_TELEGRAM_BOT_TOKEN: privateSentinels[0],
      POSTGRES_PASSWORD: privateSentinels[1],
      VPN_SALE_DATABASE_URL: privateSentinels[2],
      VPN_SALE_CUSTOMER_CSRF_SECRET: privateSentinels[3],
      VPN_SALE_IDENTITY_ENCRYPTION_KEY: privateSentinels[4],
      VPN_SALE_RATE_LIMIT_SECRET: privateSentinels[5],
    },
  });
  const output = bundleText(join(outputDirectory, "static")) + bundleText(join(outputDirectory, "server"));
  for (const sentinel of publicSentinels) assert.ok(output.includes(sentinel), `production bundle is missing ${sentinel}`);
  for (const sentinel of privateSentinels) assert.ok(!output.includes(sentinel), "production bundle contains a private sentinel");
} finally {
  rmSync(outputDirectory, { recursive: true, force: true });
}
