import "./styles.css";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>): React.ReactElement { return <html lang="fa" dir="rtl"><body>{children}</body></html>; }
