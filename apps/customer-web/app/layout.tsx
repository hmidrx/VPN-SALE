import "@vpnsale/ui/theme.css";
import Script from "next/script";
import "./customer.css";

const TELEGRAM_BRIDGE_URL = "https://telegram.org/js/telegram-web-app.js?63";
export const metadata = { title: "VPN-SALE | پنل مشتری", description: "مدیریت سرویس، کیف پول و پشتیبانی در یک تجربه امن و یکپارچه" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>): React.ReactElement {
  return <html lang="fa" dir="rtl"><head><Script src={TELEGRAM_BRIDGE_URL} strategy="beforeInteractive" /></head><body>{children}</body></html>;
}
