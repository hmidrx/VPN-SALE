import { tokens } from "@vpnsale/ui";
type AuthShellProps = { title: string; eyebrow: string; children?: React.ReactNode };

export function AuthShell(props: AuthShellProps): React.ReactElement {
  const { title, eyebrow, children } = props;
  return <main className="shell" style={{ borderRadius: tokens.radius.card }}><aside className="hero"><div className="brand">VPN-SALE</div><div className="hero-card"><p>{eyebrow}</p><h1>{title}</h1><p>ورود امن مدیران با نشست‌های سمت سرور، MFA و کنترل‌های سازمانی.</p></div><small className="ltr">Admin Security Console</small></aside><section className="main"><div className="card stack">{children}</div></section></main>;
}
export function SecurityNav(): React.ReactElement { return <nav className="nav" aria-label="ناوبری امنیت"><a className="pill" href="/security/profile">پروفایل</a><a className="pill" href="/security/sessions">نشست‌ها</a><a className="pill" href="/security/password">گذرواژه</a><a className="pill" href="/security/mfa">MFA</a></nav>; }
