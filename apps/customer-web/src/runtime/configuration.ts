import type { RuntimeConfiguration } from "./runtime-types";

export const fallbackRuntimeConfiguration: RuntimeConfiguration = {
  schema_version: 1,
  runtime_version: 0,
  brand: {
    store_name: { fa: "وی‌پی‌ان سیل", en: "VPN-SALE" },
    short_name: "VPN-SALE",
    tagline: {
      fa: "اتصال مطمئن، مدیریت شفاف",
      en: "Reliable access, transparent control",
    },
    support_username: "@support",
    support_url: "https://example.invalid/support",
    website_url: "https://example.invalid",
    mini_app_url: "https://example.invalid/app",
  },
  theme: {
    light: {
      page_color: "#f5f7fa",
      surface_color: "#ffffff",
      text_primary_color: "#172033",
      text_secondary_color: "#5d687a",
      border_color: "#d8deea",
      primary_color: "#5b72e8",
      focus_ring_color: "#4059d6",
    },
    dark: {
      page_color: "#0b0f17",
      surface_color: "#141c28",
      text_primary_color: "#f3f5fa",
      text_secondary_color: "#aeb8ca",
      border_color: "#273247",
      primary_color: "#758cff",
      focus_ring_color: "#9aa9ff",
    },
    radius: "md",
    font_family: "Vazirmatn",
    motion: "reduced-supported",
  },
  navigation: [
    {
      code: "HOME",
      label: { fa: "خانه", en: "Home" },
      destination: "HOME",
      order: 1,
    },
    {
      code: "WALLET",
      label: { fa: "کیف پول", en: "Wallet" },
      destination: "WALLET",
      order: 2,
    },
  ],
  content: {
    "customer.home": {
      fa: "به وی‌پی‌ان سیل خوش آمدید",
      en: "Welcome to VPN-SALE",
    },
  },
  feature_flags: {
    storefront: true,
    wallet: true,
    customer_web_navigation: true,
  },
  maintenance: { global: false },
};

export async function getRuntimeConfiguration(): Promise<RuntimeConfiguration> {
  const base = (
    process.env.API_INTERNAL_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    ""
  ).trim();
  if (!base) return fallbackRuntimeConfiguration;

  try {
    const endpoint = new URL(
      "/api/v1/runtime/configuration/public",
      base.endsWith("/") ? base : `${base}/`,
    );
    if (endpoint.protocol !== "http:" && endpoint.protocol !== "https:") {
      return fallbackRuntimeConfiguration;
    }
    const response = await fetch(endpoint, {
      next: { revalidate: 60 },
      signal: AbortSignal.timeout(2_500),
    });
    if (!response.ok) return fallbackRuntimeConfiguration;
    const data = (await response.json()) as RuntimeConfiguration;
    return data.schema_version === 1 ? data : fallbackRuntimeConfiguration;
  } catch {
    return fallbackRuntimeConfiguration;
  }
}
