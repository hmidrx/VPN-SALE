declare const process: { env: Record<string, string | undefined> };
export type CustomerPublicConfig = { apiBaseUrl: string; botUsername: string | null; appName: string; fakeTelegramEnabled: boolean };
export function loadCustomerConfig(env: Record<string, string | undefined> = process.env): CustomerPublicConfig {
  const fake = env.NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM === "true";
  const nodeEnv = env.NODE_ENV ?? "development";
  if (fake && nodeEnv === "production") throw new Error("Fake Telegram adapter is not allowed in production builds");
  const bot = env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME?.replace(/^@/, "").trim() || null;
  if (bot && !/^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(bot)) throw new Error("Invalid public Telegram bot username");
  return { apiBaseUrl: env.NEXT_PUBLIC_CUSTOMER_API_BASE_URL ?? env.NEXT_PUBLIC_API_BASE_URL ?? "", botUsername: bot, appName: env.NEXT_PUBLIC_CUSTOMER_APP_NAME ?? "VPN-SALE", fakeTelegramEnabled: fake };
}
