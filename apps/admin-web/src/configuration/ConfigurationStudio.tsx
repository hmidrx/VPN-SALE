"use client";
import React from "react";
import { configurationApi, type ConfigurationDraft, type ConfigurationSnapshot, type ThemeMode } from "./api";
import type { ValidationIssue } from "./types";

type Status = { tone: "ok" | "error" | "info"; text: string };
const modeFields: readonly [keyof ThemeMode, string][] = [
  ["page_color", "پس‌زمینه"],
  ["surface_color", "سطح کارت"],
  ["text_primary_color", "متن اصلی"],
  ["text_secondary_color", "متن ثانویه"],
  ["border_color", "مرزها"],
  ["primary_color", "رنگ اصلی"],
  ["focus_ring_color", "حلقه فوکوس"],
];

function issueText(issue: ValidationIssue): string { return `${issue.path}: ${issue.message}`; }

export function ConfigurationStudio(): React.ReactElement {
  const [activeVersion, setActiveVersion] = React.useState<number | null>(null);
  const [draft, setDraft] = React.useState<ConfigurationDraft | null>(null);
  const [snapshot, setSnapshot] = React.useState<ConfigurationSnapshot | null>(null);
  const [issues, setIssues] = React.useState<ValidationIssue[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [status, setStatus] = React.useState<Status>({ tone: "info", text: "در حال دریافت تنظیمات منتشرشده…" });

  React.useEffect(() => {
    void configurationApi.dashboard().then((data) => {
      setActiveVersion(data.active_version);
      setSnapshot(data.snapshot);
      setStatus({ tone: "ok", text: `نسخه ${data.active_version || "پیش‌فرض"} فعال است.` });
    }).catch((error: Error) => setStatus({ tone: "error", text: `دریافت تنظیمات انجام نشد: ${error.message}` }));
  }, []);

  const createDraft = async () => {
    setBusy(true); setIssues([]);
    try {
      const next = await configurationApi.createDraft();
      setDraft(next); setSnapshot(next.snapshot);
      setStatus({ tone: "info", text: "پیش‌نویس امن ساخته شد؛ تغییرها هنوز منتشر نشده‌اند." });
    } catch (error) { setStatus({ tone: "error", text: (error as Error).message }); }
    finally { setBusy(false); }
  };

  const setBrand = (key: keyof ConfigurationSnapshot["brand"], value: string, locale?: "fa" | "en") => {
    if (!snapshot) return;
    const brand = { ...snapshot.brand };
    if (locale) brand[key] = { ...(brand[key] as { fa: string; en: string }), [locale]: value } as never;
    else brand[key] = value as never;
    setSnapshot({ ...snapshot, brand });
  };
  const setTheme = (mode: "light" | "dark", key: keyof ThemeMode, value: string) => {
    if (!snapshot) return;
    setSnapshot({ ...snapshot, theme: { ...snapshot.theme, [mode]: { ...snapshot.theme[mode], [key]: value } } });
  };

  const saveAndValidate = async () => {
    if (!draft || !snapshot) return;
    setBusy(true); setIssues([]);
    try {
      const brandResult = await configurationApi.updateSection(draft.reference, "brand", snapshot.brand, draft.version);
      const themeResult = await configurationApi.updateSection(draft.reference, "theme", snapshot.theme, brandResult.version);
      setDraft({ ...draft, version: themeResult.version, snapshot });
      const result = await configurationApi.validate(draft.reference);
      setIssues(result.issues);
      setStatus(result.ok ? { tone: "ok", text: "اعتبارسنجی موفق بود؛ آماده انتشار است." } : { tone: "error", text: "تا رفع خطاهای زیر انتشار مسدود است." });
    } catch (error) { setStatus({ tone: "error", text: (error as Error).message }); }
    finally { setBusy(false); }
  };

  const publish = async () => {
    if (!draft || issues.some((issue) => issue.severity === "ERROR") || !confirm("نسخه اعتبارسنجی‌شده برای سایت، مینی‌اپ و ربات منتشر شود؟")) return;
    setBusy(true);
    try {
      const result = await configurationApi.publish(draft.reference);
      setActiveVersion(result.version); setDraft(null);
      setStatus({ tone: "ok", text: `نسخه ${result.version} منتشر شد. کلاینت‌ها حداکثر تا ۶۰ ثانیه تازه می‌شوند.` });
    } catch (error) { setStatus({ tone: "error", text: (error as Error).message }); }
    finally { setBusy(false); }
  };

  if (!snapshot) return <section className="config-studio"><div className="panel skeleton" aria-label={status.text} /></section>;
  return <section className="config-studio">
    <header className="config-overview panel"><div><span>نسخه فعال</span><strong>{activeVersion ?? "—"}</strong><p>تنظیمات عمومی مشترک و بدون secret</p></div><div className={`config-status config-status--${status.tone}`} role="status">{status.text}</div><button className="btn" type="button" disabled={busy || !!draft} onClick={createDraft}>ساخت پیش‌نویس جدید</button></header>
    <form onSubmit={(event) => { event.preventDefault(); void saveAndValidate(); }}>
      <fieldset disabled={!draft || busy}>
        <legend>هویت برند</legend>
        <div className="config-grid">
          <label>نام فارسی<input value={snapshot.brand.store_name.fa} onChange={(event) => setBrand("store_name", event.target.value, "fa")} /></label>
          <label>نام کوتاه<input dir="ltr" value={snapshot.brand.short_name} onChange={(event) => setBrand("short_name", event.target.value)} /></label>
          <label>شعار فارسی<input value={snapshot.brand.tagline.fa} onChange={(event) => setBrand("tagline", event.target.value, "fa")} /></label>
          <label>نام پشتیبانی<input dir="ltr" value={snapshot.brand.support_username} onChange={(event) => setBrand("support_username", event.target.value)} /></label>
          <label>آدرس سایت<input dir="ltr" type="url" value={snapshot.brand.website_url} onChange={(event) => setBrand("website_url", event.target.value)} /></label>
          <label>آدرس مینی‌اپ<input dir="ltr" type="url" value={snapshot.brand.mini_app_url} onChange={(event) => setBrand("mini_app_url", event.target.value)} /></label>
        </div>
      </fieldset>
      <div className="config-themes">
        {(["dark", "light"] as const).map((mode) => <fieldset key={mode} disabled={!draft || busy}><legend>{mode === "dark" ? "تم تاریک" : "تم روشن"}</legend><div className="theme-controls">{modeFields.map(([key, label]) => <label key={key}><span>{label}</span><input type="color" value={snapshot.theme[mode][key] ?? "#000000"} onChange={(event) => setTheme(mode, key, event.target.value)} /><code>{snapshot.theme[mode][key] ?? "—"}</code></label>)}</div></fieldset>)}
      </div>
      {issues.length ? <section className="config-issues" aria-label="خطاهای اعتبارسنجی">{issues.map((issue) => <p key={issue.code + issue.path}>{issueText(issue)}</p>)}</section> : null}
      <div className="actions"><button className="btn secondary" type="submit" disabled={!draft || busy}>ذخیره و اعتبارسنجی</button><button className="btn" type="button" disabled={!draft || busy || issues.some((issue) => issue.severity === "ERROR")} onClick={() => void publish()}>انتشار برای همه سطوح</button></div>
    </form>
  </section>;
}
