import { Card, PageHeader } from "@vpnsale/ui";
type AuthShellProps = { title: string; eyebrow: string; children?: React.ReactNode };

export function AuthShell(props: AuthShellProps): React.ReactElement {
  const { title, eyebrow, children } = props;
  return <main className="auth-layout auth-layout--admin"><aside className="auth-brand"><strong>DR•PING</strong><p>کنسول امنیت و عملیات مدیریت</p><small>ورود مدیران به تأیید دومرحله‌ای نیاز دارد و هرگز تنها بر هویت تلگرام متکی نیست.</small></aside><Card className="auth-card"><PageHeader eyebrow={eyebrow} title={title}/>{children}</Card></main>;
}
export function SecurityNav(): React.ReactElement { return <nav className="nav" aria-label="ناوبری امنیت"><a className="pill" href="/security/profile">پروفایل</a><a className="pill" href="/security/sessions">نشست‌ها</a><a className="pill" href="/security/password">گذرواژه</a><a className="pill" href="/security/mfa">MFA</a></nav>; }
