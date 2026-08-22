"use client";

import React from "react";
import { getProfile } from "../auth/api-client";
import { effectivePermissions, visibleNav, type NavItem } from "../management/permissions";
import { fa } from "../i18n/management";

type Props = { title: string; eyebrow?: string; children?: React.ReactNode; required?: string };

const operationalNav: NavItem[] = [
  { href: "/management/operations/readiness", label: "سلامت و آمادگی", permissions: ["operations.read", "operations.readiness.read"] },
  { href: "/management/services", label: "سرویس‌ها", permissions: ["services.read"] },
  { href: "/management/orders", label: "سفارش‌ها", permissions: ["orders.read"] },
  { href: "/management/manual-topups", label: "واریزهای دستی", permissions: ["manual_topups.read"] },
  { href: "/support", label: "پشتیبانی", permissions: ["support.read", "support.manage"] },
  { href: "/management/configuration", label: "سایت و مینی‌اپ", permissions: ["configuration.read", "configuration.manage"] },
];

function canSee(item: NavItem, permissions: Set<string>): boolean {
  return item.permissions.length === 0 || item.permissions.some((permission) => permissions.has(permission));
}

export function ManagementShell({ title, eyebrow = "کنترل عملیات", children, required }: Props): React.ReactElement {
  const [permissions, setPermissions] = React.useState<Set<string> | null>(null);
  React.useEffect(() => { void getProfile().then((profile) => setPermissions(effectivePermissions(profile))).catch(() => setPermissions(new Set())); }, []);
  const primary = permissions ? visibleNav(permissions) : [];
  const operations = permissions ? operationalNav.filter((item) => canSee(item, permissions)) : [];
  return <main className="mgmt-shell"><aside className="mgmt-side"><a className="admin-brand" href="/management" aria-label="مرکز فرماندهی VPN-SALE"><span>V</span><div><b>VPN—SALE</b><small>OWNER CONTROL</small></div></a><div className="mgmt-nav-group"><p>مدیریت اصلی</p><nav aria-label="ناوبری اصلی مدیریت" className="mgmt-nav">{primary.map((item)=><a key={item.href} href={item.href}>{item.label}</a>)}</nav></div>{operations.length ? <div className="mgmt-nav-group"><p>عملیات کسب‌وکار</p><nav aria-label="ناوبری عملیات" className="mgmt-nav">{operations.map((item)=><a key={item.href} href={item.href}>{item.label}</a>)}</nav></div> : null}<div className="mgmt-session"><i/><div><b>نشست محافظت‌شده</b><small>مجوزها از سرور دریافت شد</small></div></div></aside><section className="mgmt-main"><header className="mgmt-top"><div><p className="eyebrow">{required ? `مجوز: ${required}` : eyebrow}</p><h1>{title}</h1></div><div className="mgmt-top-actions"><a className="pill" href="/management/security-events">مرکز هشدار</a><a className="admin-profile" href="/security/profile"><span>H</span><div><b>حساب مالک</b><small>{fa.nav.personal}</small></div></a></div></header>{children}</section></main>;
}

export function StatusBadge({ value }: { value?: string | boolean | null }): React.ReactElement { return <span className="status"><span aria-hidden="true">●</span>{String(value ?? "—")}</span>; }
export function Tech({ children }: { children?: React.ReactNode }): React.ReactElement { return <code className="tech" dir="ltr">{children ?? "—"}</code>; }
export function EmptyState({ title, body }: { title: string; body: string }): React.ReactElement { return <section className="empty"><h2>{title}</h2><p>{body}</p></section>; }
export function ConfirmBox({ label = "علت عملیات", action = "تأیید عملیات حساس" }: { label?: string; action?: string }): React.ReactElement { return <form className="confirm" aria-label="تأیید عملیات"><label>{label}<textarea maxLength={240} required /></label><button className="btn danger" type="button">{action}</button></form>; }
