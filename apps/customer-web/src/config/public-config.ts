declare const process: { env: Record<string, string | undefined> };

export type CustomerPublicEnvironment = {
  NODE_ENV?: string;
  NEXT_PUBLIC_API_BASE_URL?: string;
  NEXT_PUBLIC_CUSTOMER_API_BASE_URL?: string;
  NEXT_PUBLIC_TELEGRAM_BOT_USERNAME?: string;
  NEXT_PUBLIC_CUSTOMER_APP_NAME?: string;
  NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM?: string;
};

export type CustomerPublicConfig = {
  apiBaseUrl: string;
  botUsername: string | null;
  appName: string;
  fakeTelegramEnabled: boolean;
};

// These direct accesses are intentionally explicit: Next.js replaces public values at build time.
const compiledCustomerEnvironment: CustomerPublicEnvironment = {
  NODE_ENV: process.env.NODE_ENV,
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  NEXT_PUBLIC_CUSTOMER_API_BASE_URL:
    process.env.NEXT_PUBLIC_CUSTOMER_API_BASE_URL,
  NEXT_PUBLIC_TELEGRAM_BOT_USERNAME:
    process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME,
  NEXT_PUBLIC_CUSTOMER_APP_NAME: process.env.NEXT_PUBLIC_CUSTOMER_APP_NAME,
  NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM:
    process.env.NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM,
};

export function parseCustomerConfig(
  env: CustomerPublicEnvironment,
): CustomerPublicConfig {
  const fake = env.NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM === "true";
  const nodeEnv = env.NODE_ENV ?? "development";
  if (fake && nodeEnv === "production") {
    throw new Error("Fake Telegram adapter is not allowed in production builds");
  }

  const bot =
    env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME?.replace(/^@/, "").trim() || null;
  if (bot && !/^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(bot)) {
    throw new Error("Invalid public Telegram bot username");
  }

  return {
    apiBaseUrl:
      env.NEXT_PUBLIC_CUSTOMER_API_BASE_URL ??
      env.NEXT_PUBLIC_API_BASE_URL ??
      "",
    botUsername: bot,
    appName: env.NEXT_PUBLIC_CUSTOMER_APP_NAME ?? "VPN-SALE",
    fakeTelegramEnabled: fake,
  };
}

export function loadCustomerConfig(): CustomerPublicConfig {
  return parseCustomerConfig(compiledCustomerEnvironment);
}
