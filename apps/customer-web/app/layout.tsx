import "@vpnsale/ui/theme.css";
import type { CSSProperties } from "react";
import type { Metadata } from "next";
import Script from "next/script";
import "./customer.css";
import { getRuntimeConfiguration } from "../src/runtime/configuration";
import { RuntimeConfigurationProvider } from "../src/runtime/RuntimeConfigurationProvider";

const TELEGRAM_BRIDGE_URL = "https://telegram.org/js/telegram-web-app.js?63";

export async function generateMetadata(): Promise<Metadata> {
  const configuration = await getRuntimeConfiguration();
  return {
    title: `${configuration.brand.short_name} | پنل مشتری`,
    description: configuration.brand.tagline.fa,
  };
}

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>): Promise<React.ReactElement> {
  const configuration = await getRuntimeConfiguration();
  const theme = configuration.theme.dark;
  const style = {
    "--color-canvas": theme.page_color,
    "--color-surface": theme.surface_color,
    "--color-surface-raised": theme.surface_color,
    "--color-surface-interactive": theme.surface_color,
    "--color-text": theme.text_primary_color,
    "--color-text-muted": theme.text_secondary_color,
    "--color-border": theme.border_color,
    "--color-primary": theme.primary_color,
    "--color-focus": theme.focus_ring_color,
  } as CSSProperties;
  return <html lang="fa" dir="rtl" data-runtime-version={configuration.runtime_version} style={style}><head><Script src={TELEGRAM_BRIDGE_URL} strategy="beforeInteractive" /></head><body><RuntimeConfigurationProvider value={configuration} children={children} /></body></html>;
}
