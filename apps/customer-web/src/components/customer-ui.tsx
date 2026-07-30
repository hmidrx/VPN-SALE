"use client";

import React from "react";

export function PageShell({ children, labelledBy }: { children: React.ReactNode; labelledBy: string }): React.ReactElement {
  return <section className="page-shell" aria-labelledby={labelledBy}>{children}</section>;
}

export function PageHeader({ title, subtitle, backHref, action }: { title: string; subtitle?: string; backHref?: string; action?: React.ReactNode }): React.ReactElement {
  return <header className="page-header">
    {backHref ? <a className="icon-button" href={backHref} aria-label="بازگشت"><span aria-hidden="true">→</span></a> : null}
    <div><h1 id="page-title">{title}</h1>{subtitle ? <p>{subtitle}</p> : null}</div>
    {action ? <div className="page-header__action">{action}</div> : null}
  </header>;
}

export function PremiumCard({ children, className = "" }: { children: React.ReactNode; className?: string }): React.ReactElement {
  return <article className={`premium-card ${className}`.trim()}>{children}</article>;
}

export function StatusBadge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "success" | "warning" | "danger" | "neutral" }): React.ReactElement {
  return <span className="status-badge" data-tone={tone}>{children}</span>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }): React.ReactElement {
  return <div className="empty-state"><span className="empty-state__icon" aria-hidden="true">◇</span><h2>{title}</h2><p>{description}</p>{action}</div>;
}

export function ErrorState({ title = "امکان دریافت اطلاعات نیست", onRetry }: { title?: string; onRetry: () => void }): React.ReactElement {
  return <div className="error-state" role="alert"><h2>{title}</h2><p>اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.</p><button className="ui-button" type="button" onClick={onRetry}>تلاش دوباره</button></div>;
}

export function InlineNotice({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "warning" | "danger" }): React.ReactElement {
  return <div className="inline-notice" data-tone={tone} role="status">{children}</div>;
}

export function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }): React.ReactElement {
  return <div className="section-header"><h2>{title}</h2>{action}</div>;
}

export function ListRow({ title, description, value }: { title: string; description?: string; value?: React.ReactNode }): React.ReactElement {
  return <div className="list-row"><div><strong>{title}</strong>{description ? <small>{description}</small> : null}</div>{value ? <span>{value}</span> : null}</div>;
}
