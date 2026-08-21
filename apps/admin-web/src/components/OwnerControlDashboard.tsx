"use client";

import React from "react";
import { managementApi, type OperationsHealthSnapshot } from "../management/api";
import { EmptyState, StatusBadge } from "./ManagementShell";

function Icon({ path }: { path: string }): React.ReactElement {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d={path} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" /></svg>;
}

const icons = {
  bot: "M12 4V2m-5 7h10a3 3 0 0 1 3 3v6H4v-6a3 3 0 0 1 3-3Zm2 4h.01M15 13h.01M8 18v3m8-3v3",
  worker: "M5 5h14v6H5zM5 15h14v4H5zM8 8h.01M8 17h.01",
  queue: "M4 7h16M4 12h12M4 17h8",
  shield: "M12 3 20 6v5c0 5-3.4 8.7-8 10-4.6-1.3-8-5-8-10V6l8-3Zm-3 9 2 2 4-5",
  support: "M5 13v-1a7 7 0 0 1 14 0v1m-14 0v5h3v-5H5Zm14 0v5h-3v-5h3Z",
};

function humanStatus(status: OperationsHealthSnapshot["status"]): string {
  return status === "HEALTHY" ? "پایدار" : status === "DEGRADED" ? "نیازمند بررسی" : "نیازمند اقدام";
}

function Metric({ icon, label, value, hint, urgent = false }: { icon: string; label: string; value: string | number; hint: string; urgent?: boolean }): React.ReactElement {
  return <article className={urgent ? "owner-metric owner-metric--urgent" : "owner-metric"}><span className="owner-metric__icon"><Icon path={icon} /></span><div><small>{label}</small><strong>{value}</strong><p>{hint}</p></div></article>;
}

function Surface({ title, subtitle, href, children }: { title: string; subtitle: string; href?: string; children: React.ReactNode }): React.ReactElement {
  return <section className="owner-surface"><header><div><h2>{title}</h2><p>{subtitle}</p></div>{href ? <a href={href}>مشاهده کامل ←</a> : null}</header>{children}</section>;
}

export function OwnerControlDashboard(): React.ReactElement {
  const [snapshot, setSnapshot] = React.useState<OperationsHealthSnapshot | null>(null);
  const [state, setState] = React.useState<"loading" | "ready" | "error">("loading");
  const load = React.useCallback(() => {
    setState("loading");
    void managementApi.operationsHealth().then((value) => { setSnapshot(value); setState("ready"); }).catch(() => setState("error"));
  }, []);
  React.useEffect(load, [load]);

  if (state === "loading") return <section className="owner-loading" aria-label="در حال دریافت وضعیت"><span className="skeleton"/><span className="skeleton"/><span className="skeleton"/></section>;
  if (state === "error" || !snapshot) return <EmptyState title="دریافت وضعیت ممکن نشد" body="اتصال API یا مجوز operations.read را بررسی کنید؛ هیچ وضعیت ساختگی نمایش داده نمی‌شود." />;

  const attention = snapshot.outbox.failed + snapshot.fulfillment.failed + snapshot.fulfillment.operator_review + snapshot.service_operations.review_required;
  return <div className="owner-dashboard">
    <section className="owner-command"><div className="owner-command__pulse"><Icon path={icons.shield}/></div><div><span>وضعیت کل سامانه</span><h2>{humanStatus(snapshot.status)}</h2><p>{snapshot.signals.length ? `${snapshot.signals.length.toLocaleString("fa-IR")} سیگنال عملیاتی ثبت شده است.` : "Worker، صف‌ها و عملیات سرویس بدون هشدار فعال هستند."}</p></div><div className="owner-command__meta"><StatusBadge value={humanStatus(snapshot.status)} /><button className="btn secondary" type="button" onClick={load}>به‌روزرسانی</button></div></section>
    <section className="owner-metrics"><Metric icon={icons.worker} label="Worker اصلی" value={snapshot.worker.state === "RUNNING" ? "فعال" : snapshot.worker.state} hint={snapshot.worker.last_seen_age_seconds === null ? "زمان heartbeat نامشخص" : `${snapshot.worker.last_seen_age_seconds.toLocaleString("fa-IR")} ثانیه از heartbeat`} urgent={snapshot.worker.state !== "RUNNING"}/><Metric icon={icons.queue} label="صف آماده پردازش" value={snapshot.outbox.pending_due.toLocaleString("fa-IR")} hint={`${snapshot.outbox.retrying.toLocaleString("fa-IR")} مورد در تلاش مجدد`} urgent={snapshot.outbox.failed > 0}/><Metric icon={icons.bot} label="عملیات سرویس" value={snapshot.service_operations.in_progress.toLocaleString("fa-IR")} hint={`${snapshot.service_operations.review_required.toLocaleString("fa-IR")} مورد نیازمند بررسی`} urgent={snapshot.service_operations.review_required > 0}/><Metric icon={icons.support} label="نیازمند اقدام" value={attention.toLocaleString("fa-IR")} hint="خطاها و بازبینی‌های عملیاتی" urgent={attention > 0}/></section>
    <div className="owner-dashboard__grid"><Surface title="کانال‌ها و زیرساخت" subtitle="نمای واحد سایت، ربات، مینی‌اپ و Worker" href="/management/operations/readiness"><div className="owner-systems"><a href="/management/operations/readiness"><span><Icon path={icons.bot}/></span><div><b>ربات تلگرام</b><small>وضعیت از Worker و صف رویدادها</small></div><StatusBadge value={snapshot.worker.state}/></a><a href="/management/configuration"><span><Icon path={icons.shield}/></span><div><b>سایت و مینی‌اپ</b><small>پیکربندی و نسخه فعال</small></div><span className="owner-link">مدیریت ←</span></a><a href="/management/providers"><span><Icon path={icons.worker}/></span><div><b>پنل‌ها و Provider</b><small>سلامت، ظرفیت و همگام‌سازی</small></div><span className="owner-link">بررسی ←</span></a><a href="/support"><span><Icon path={icons.support}/></span><div><b>پشتیبانی</b><small>صف تیکت‌ها و SLA</small></div><span className="owner-link">ورود ←</span></a></div></Surface>
    <Surface title="مصرف و تحویل" subtitle="اعداد مرجع از پایگاه‌داده و همگام‌سازی Provider"><dl className="owner-health-list"><div><dt>آخرین وضعیت مصرف</dt><dd><StatusBadge value={snapshot.usage_sync.latest_status}/></dd></div><div><dt>حساب‌های با داده قدیمی</dt><dd>{snapshot.usage_sync.stale_active_accounts.toLocaleString("fa-IR")}</dd></div><div><dt>تحویل در تلاش مجدد</dt><dd>{snapshot.fulfillment.retry_pending.toLocaleString("fa-IR")}</dd></div><div><dt>تحویل نیازمند اپراتور</dt><dd>{snapshot.fulfillment.operator_review.toLocaleString("fa-IR")}</dd></div></dl></Surface>
    <Surface title="دسترسی سریع مالک" subtitle="عملیات پرتکرار با کنترل مجوز و ثبت حسابرسی"><div className="owner-quick"><a href="/management/customers">مدیریت کاربران <span>←</span></a><a href="/management/manual-topups">بررسی واریزها <span>←</span></a><a href="/management/services">مدیریت سرویس‌ها <span>←</span></a><a href="/management/security-events">رویدادهای امنیتی <span>←</span></a></div></Surface>
    <Surface title="سیگنال‌های عملیاتی" subtitle="شناسه‌های محدود و بدون داده حساس"><div className="owner-signals">{snapshot.signals.length ? snapshot.signals.map((signal) => <code key={signal}>{signal}</code>) : <p>هشدار فعالی وجود ندارد.</p>}</div></Surface></div>
  </div>;
}
