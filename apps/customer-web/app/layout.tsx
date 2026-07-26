import "@vpnsale/ui/theme.css";
export const metadata = { title: "VPN-SALE Customer", description: "Telegram Mini App customer shell" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>): React.ReactElement { return <html lang="fa" dir="rtl"><body>{children}</body></html>; }
