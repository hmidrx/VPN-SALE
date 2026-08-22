"use client";

import React from "react";
import { useRuntimeConfiguration } from "../runtime/RuntimeConfigurationProvider";

type IconName = "shield" | "bolt" | "chart" | "headset" | "wallet" | "devices" | "arrow" | "sun" | "moon" | "check";

const paths: Record<IconName, string> = {
  shield: "M12 3 20 7v5c0 5-3.4 8.1-8 10-4.6-1.9-8-5-8-10V7l8-4Zm-3.2 9.2 2.1 2.1 4.6-5",
  bolt: "m13 2-8 12h6l-1 8 9-13h-6V2Z",
  chart: "M4 19V9m6 10V5m6 14v-7m4 7H2",
  headset: "M4 14v-2a8 8 0 0 1 16 0v2m-16-1v5h4v-5H4Zm16 0v5h-4v-5h4Z",
  wallet: "M4 7a3 3 0 0 1 3-3h11v16H6a2 2 0 0 1-2-2V7Zm0 1h14m-5 5h7v4h-7",
  devices: "M4 5h12v10H4V5Zm3 14h6m-3-4v4m9-9h2v9h-6v-2",
  arrow: "m9 5 7 7-7 7m7-7H3",
  sun: "M12 3v2m0 14v2m9-9h-2M5 12H3m15.4-6.4-1.4 1.4M7 17l-1.4 1.4m12.8 0L17 17M7 7 5.6 5.6M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  moon: "M20 15.3A8 8 0 0 1 8.7 4a8 8 0 1 0 11.3 11.3Z",
  check: "m5 12 4 4L19 6",
};

function Icon({ name, className }: { name: IconName; className?: string }): React.ReactElement {
  return <svg aria-hidden="true" className={className} viewBox="0 0 24 24"><path d={paths[name]} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" /></svg>;
}

function Brand({ compact = false }: { compact?: boolean }): React.ReactElement {
  const { brand } = useRuntimeConfiguration();
  const [imageFailed, setImageFailed] = React.useState(false);
  const logo = brand.logo_asset_reference ? `/api/v1/runtime/configuration/media/${encodeURIComponent(brand.logo_asset_reference)}` : "";
  return <span className={`brand-lockup${compact ? " brand-lockup--compact" : ""}`}>
    {logo && !imageFailed ? <img src={logo} alt={brand.logo_alt_text || `لوگوی ${brand.short_name}`} onError={() => setImageFailed(true)} /> : <span className="brand-mark" aria-hidden="true"><Icon name="shield" /></span>}
    <span><strong>{brand.short_name}</strong>{compact ? null : <small>{brand.tagline.fa}</small>}</span>
  </span>;
}

const advantages = [
  { icon: "chart" as const, title: "مصرف شفاف", text: "حجم باقی‌مانده و زمان آخرین همگام‌سازی را بدون عددسازی ببین." },
  { icon: "bolt" as const, title: "مدیریت بی‌دردسر", text: "تمدید و افزایش حجم فقط با قیمت تأییدشده‌ی سرور انجام می‌شود." },
  { icon: "headset" as const, title: "پشتیبانی یکپارچه", text: "تیکت‌ها و پاسخ‌ها در سایت، مینی‌اپ و ربات به یک حساب متصل‌اند." },
  { icon: "shield" as const, title: "تحویل امن", text: "لینک اشتراک و اطلاعات اتصال فقط در جریان امن حساب نمایش داده می‌شود." },
];

const plans = [
  { eyebrow: "برای شروع", title: "انعطاف‌پذیر", text: "انتخاب حجم، مدت و موقعیت از فهرست واقعی و به‌روز.", points: ["قیمت نهایی از سرور", "پرداخت با کیف پول", "فعال‌سازی قابل پیگیری"] },
  { eyebrow: "انتخاب متعادل", title: "پیشنهاد هوشمند", text: "مقایسه‌ی ساده‌ی پلن‌ها بدون جدول‌های پیچیده و عددهای نمایشی.", points: ["مقایسه تا سه پلن", "نمایش محدودیت‌ها", "خلاصه پیش از پرداخت"], featured: true },
  { eyebrow: "برای چند دستگاه", title: "ظرفیت بیشتر", text: "پلن مناسب مصرف بالاتر را بر اساس گزینه‌های موجود پیدا کن.", points: ["جزئیات دستگاه‌ها", "وضعیت سرویس روشن", "مدیریت از هر سه سطح"] },
];

export function MarketingLanding(): React.ReactElement {
  const runtime = useRuntimeConfiguration();
  const [theme, setTheme] = React.useState<"dark" | "light">("dark");
  React.useEffect(() => {
    const preferred = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    setTheme(preferred);
    document.documentElement.dataset.theme = preferred;
  }, []);
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
  };
  const supportHref = runtime.brand.support_url.includes("example.invalid") ? "/support" : runtime.brand.support_url;
  return <div className="marketing">
    <header className="marketing-header">
      <a href="#top" className="marketing-brand" aria-label={`صفحه نخست ${runtime.brand.short_name}`}><Brand /></a>
      <nav aria-label="ناوبری صفحه اصلی">
        <a href="#advantages">امکانات</a><a href="#plans">پلن‌ها</a><a href="#steps">شروع کار</a><a href="#faq">سؤالات</a>
      </nav>
      <div className="marketing-header__actions">
        <button className="theme-switch" type="button" aria-label={theme === "dark" ? "فعال‌کردن تم روشن" : "فعال‌کردن تم تاریک"} aria-pressed={theme === "light"} onClick={toggleTheme}><Icon name={theme === "dark" ? "sun" : "moon"} /></button>
        <a className="text-link" href="/auth/sign-in">ورود</a>
        <a className="marketing-button marketing-button--small" href="/auth/register">ساخت حساب</a>
      </div>
    </header>

    <main id="top">
      <section className="cinematic-hero">
        <div className="hero-aura" aria-hidden="true" />
        <div className="hero-copy">
          <span className="hero-kicker"><i /> یک حساب؛ سایت، ربات و مینی‌اپ</span>
          <h1>اتصال مطمئن،<br /><span>کنترل کامل.</span></h1>
          <p>{runtime.brand.tagline.fa}؛ خرید، تحویل، مصرف، تمدید و پشتیبانی در یک تجربه‌ی فارسی و هماهنگ.</p>
          <div className="hero-actions">
            <a className="marketing-button" href="/catalog/products">مشاهده پلن‌های واقعی <Icon name="arrow" /></a>
            <a className="marketing-button marketing-button--ghost" href="/app">ورود به پنل مشتری</a>
          </div>
          <ul className="hero-proof" aria-label="ویژگی‌های اصلی">
            <li><Icon name="shield" /><span><b>امن</b><small>تحویل حساس فقط داخل حساب</small></span></li>
            <li><Icon name="devices" /><span><b>هماهنگ</b><small>وب، تلگرام و مینی‌اپ</small></span></li>
            <li><Icon name="headset" /><span><b>در دسترس</b><small>پشتیبانی و پیگیری یک‌جا</small></span></li>
          </ul>
        </div>

        <div className="hero-system" aria-label="نمایش مفهومی وضعیت سرویس">
          <div className="system-orbit system-orbit--one" aria-hidden="true" />
          <div className="system-orbit system-orbit--two" aria-hidden="true" />
          <article className="network-console">
            <header><Brand compact /><span className="live-pill"><i /> متصل</span></header>
            <div className="network-map" aria-hidden="true">
              <svg viewBox="0 0 420 190" preserveAspectRatio="none">
                <path className="network-path network-path--muted" d="M24 140C98 20 175 184 246 72s112 6 150-34" />
                <path className="network-path" d="M24 140C98 20 175 184 246 72s112 6 150-34" />
                <circle cx="24" cy="140" r="5" /><circle cx="246" cy="72" r="5" /><circle cx="396" cy="38" r="6" />
              </svg>
              <span className="node-label node-label--customer">دستگاه شما</span>
              <span className="node-label node-label--server">مسیر امن</span>
            </div>
            <div className="console-metrics">
              <div><span>وضعیت سرویس</span><strong>آماده</strong></div>
              <div><span>گزارش مصرف</span><strong>شفاف</strong></div>
              <div><span>مدیریت حساب</span><strong>یکپارچه</strong></div>
            </div>
            <footer><span><i /> اطلاعات واقعی بعد از ورود</span><a href="/services">مدیریت سرویس <Icon name="arrow" /></a></footer>
          </article>
          <aside className="floating-signal floating-signal--top"><Icon name="bolt" /><span><b>عملیات سریع</b><small>بدون حدس قیمت</small></span></aside>
          <aside className="floating-signal floating-signal--bottom"><Icon name="chart" /><span><b>مصرف معتبر</b><small>با زمان همگام‌سازی</small></span></aside>
        </div>
      </section>

      <section className="platform-strip" aria-label="پلتفرم‌های قابل استفاده">
        <span>قابل مدیریت از</span><b>Android</b><b>iOS</b><b>Windows</b><b>macOS</b><b>Linux</b><b>Telegram</b>
      </section>

      <section className="marketing-section advantages" id="advantages">
        <header className="section-intro"><span>همه چیز سر جای خودش</span><h2>کمتر درگیر تنظیمات شو؛<br />بیشتر از سرویس استفاده کن.</h2><p>اطلاعات مهم، عملیات پرکاربرد و پشتیبانی بدون اصطلاحات فنی اضافه در دسترس‌اند.</p></header>
        <div className="advantage-grid">
          {advantages.map((item, index) => <article className={index === 0 ? "advantage-card advantage-card--wide" : "advantage-card"} key={item.title}><span className="feature-index">۰{index + 1}</span><span className="feature-icon"><Icon name={item.icon} /></span><h3>{item.title}</h3><p>{item.text}</p>{index === 0 ? <div className="mini-chart" aria-hidden="true"><i /><i /><i /><i /><i /></div> : null}</article>)}
        </div>
      </section>

      <section className="marketing-section plans" id="plans">
        <header className="section-intro section-intro--center"><span>انتخاب بدون ابهام</span><h2>پلنی که با مصرف تو جور است.</h2><p>مبلغ، موجودی و امکان خرید فقط از پاسخ معتبر سرور نمایش داده می‌شوند.</p></header>
        <div className="plan-grid">
          {plans.map((plan) => <article className={plan.featured ? "plan-card plan-card--featured" : "plan-card"} key={plan.title}><header><span>{plan.eyebrow}</span>{plan.featured ? <b>پیشنهادی</b> : null}</header><h3>{plan.title}</h3><p>{plan.text}</p><ul>{plan.points.map(point => <li key={point}><Icon name="check" />{point}</li>)}</ul><a href="/catalog/products">مشاهده گزینه‌های موجود <Icon name="arrow" /></a></article>)}
        </div>
      </section>

      <section className="marketing-section steps" id="steps">
        <header className="section-intro"><span>شروع ساده</span><h2>از انتخاب تا اتصال، سه قدم روشن.</h2></header>
        <ol className="step-flow">
          <li><span>۱</span><div><h3>پلن را انتخاب کن</h3><p>حجم، مدت، موقعیت و محدودیت‌های واقعی را مقایسه کن.</p></div></li>
          <li><span>۲</span><div><h3>پرداخت را تأیید کن</h3><p>خلاصه سفارش و مبلغ نهایی پیش از برداشت نمایش داده می‌شود.</p></div></li>
          <li><span>۳</span><div><h3>اتصال را تحویل بگیر</h3><p>وضعیت آماده‌سازی و اطلاعات امن اتصال را از حساب پیگیری کن.</p></div></li>
        </ol>
      </section>

      <section className="marketing-section faq" id="faq">
        <header className="section-intro"><span>پاسخ‌های کوتاه</span><h2>سؤال‌های مهم، جواب‌های روشن.</h2></header>
        <div className="faq-list">
          <details><summary>اطلاعات مصرف چقدر قابل اعتماد است؟<span /></summary><p>فقط داده‌ای نمایش داده می‌شود که منبع و زمان همگام‌سازی معتبر داشته باشد؛ وضعیت قدیمی یا نامطمئن به‌صورت «در دسترس نیست» مشخص می‌شود.</p></details>
          <details><summary>سایت و ربات حساب جدا دارند؟<span /></summary><p>خیر. سایت، مینی‌اپ و ربات به همان حساب، کیف پول، سرویس و تیکت‌های مشترک متصل‌اند.</p></details>
          <details><summary>تمدید یا افزایش حجم چطور انجام می‌شود؟<span /></summary><p>ابتدا امکان انجام عملیات و قیمت نهایی از سرور بررسی می‌شود؛ سپس با تأیید شما پرداخت و اجرا قابل پیگیری است.</p></details>
        </div>
      </section>

      <section className="final-cta">
        <div><span>آماده‌ای شروع کنی؟</span><h2>سرویس را ساده بخر؛<br />حرفه‌ای مدیریت کن.</h2><p>بدون عدد نمایشی و وعده‌ی ساختگی؛ همه‌چیز بر اساس وضعیت واقعی حساب تو.</p></div>
        <div><a className="marketing-button" href="/auth/register">ساخت حساب <Icon name="arrow" /></a><a className="marketing-button marketing-button--ghost" href={supportHref}>گفت‌وگو با پشتیبانی</a></div>
      </section>
    </main>

    <footer className="marketing-footer"><Brand compact /><nav><a href="/app">پنل مشتری</a><a href="/status">وضعیت سامانه</a><a href="/education">راهنمای اتصال</a><a href={supportHref}>پشتیبانی</a></nav><small>© {new Date().getFullYear()} {runtime.brand.short_name}</small></footer>
  </div>;
}
