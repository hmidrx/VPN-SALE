import { tokens } from "@vpnsale/ui";
import {
  demoResellerPortal,
  formatRial,
  formatTomanPresentation,
  resellerNavigation,
  storagePolicyChecklist,
  validateBrandingDraft,
  validateRemarkTemplate,
} from "./reseller-portal";

const portal = demoResellerPortal;
const remarkValidation = validateRemarkTemplate(portal.remark.template);
const brandingValidation = validateBrandingDraft(portal.brandingDraft);

function StatusPill({ label, tone }: Readonly<{ label: string; tone: "good" | "warn" | "info" }>): React.ReactElement {
  const background = tone === "good" ? "#dcfce7" : tone === "warn" ? "#fef3c7" : "#dbeafe";
  const color = tone === "good" ? "#166534" : tone === "warn" ? "#92400e" : "#1e40af";
  return <span className="pill" style={{ background, color }}>{label}</span>;
}

function Money({ amount }: Readonly<{ amount: number }>): React.ReactElement {
  return <span className="money" dir="ltr" aria-label={`${formatRial(amount)}، معادل نمایشی ${formatTomanPresentation(amount)}`}>{formatRial(amount)} <small>({formatTomanPresentation(amount)})</small></span>;
}

export default function Page(): React.ReactElement {
  return (
    <main className="portal-shell" style={{ background: tokens.color.bg }}>
      <aside className="sidebar" aria-label="ناوبری فروشنده">
        <div className="brand-block">
          <span className="brand-mark" aria-hidden="true">VS</span>
          <div>
            <p>VPN-SALE</p>
            <strong>{portal.brandingDraft.displayBrand}</strong>
          </div>
        </div>
        <nav>
          {resellerNavigation.map((item) => <a key={item.href} href={item.href}>{item.label}</a>)}
        </nav>
      </aside>

      <section className="content" aria-labelledby="portal-title">
        <header className="hero">
          <div>
            <p className="eyebrow">پرتال فروشنده · Milestone 5-D</p>
            <h1 id="portal-title">داشبورد عمده‌فروشی و سفارش‌های تأمین‌شده توسط فروشنده</h1>
            <p>تمام قیمت‌ها از API فروشنده خوانده می‌شوند؛ مبلغ معتبر فقط ریال عدد صحیح است و تومان صرفاً نمایش کمکی است.</p>
          </div>
          <div className="hero-actions">
            <StatusPill label={`وضعیت: ${portal.account.status}`} tone="good" />
            <StatusPill label={`سطح: ${portal.account.tier}`} tone="info" />
          </div>
        </header>

        <section className="grid cards" aria-label="خلاصه عملیاتی">
          <article><span>موجودی قابل استفاده</span><strong><Money amount={portal.wallet.availableRial} /></strong><small>رزروشده: <Money amount={portal.wallet.reservedRial} /></small></article>
          <article><span>اعتبار کنترل‌شده</span><strong><Money amount={portal.credit.availableRial} /></strong><small>مصرف‌شده: <Money amount={portal.credit.utilizedRial} /></small></article>
          <article><span>مشتریان مدیریت‌شده</span><strong>{portal.customers.usedQuota} / {portal.customers.maxQuota}</strong><small>ایجاد و دعوت فقط برای حساب ACTIVE فعال است.</small></article>
          <article><span>سفارش‌های در انتظار</span><strong>{portal.orders.pendingCount}</strong><small>هیچ سفارش آماده‌سازی به‌عنوان تحویل‌شده نمایش داده نمی‌شود.</small></article>
        </section>

        <section className="panel" id="catalog">
          <div className="section-heading"><h2>کاتالوگ عمده و قیمت‌گذاری معتبر</h2><StatusPill label="Backend authoritative" tone="info" /></div>
          <div className="table-wrap"><table><thead><tr><th>محصول</th><th>نسخه</th><th>شرایط</th><th>قیمت عمده</th><th>بازه خرده‌فروشی</th><th>وضعیت</th></tr></thead><tbody>
            {portal.catalog.map((product) => <tr key={product.id}><td><strong>{product.name}</strong><small>{product.description}</small></td><td dir="ltr">{product.version}</td><td>{product.durationDays} روز · {product.trafficGb}GB · {product.deviceLimit} دستگاه</td><td><Money amount={product.wholesaleRial} /></td><td><Money amount={product.minRetailRial} /> تا <Money amount={product.maxRetailRial} /></td><td><StatusPill label={product.available ? "قابل سفارش" : "غیرفعال"} tone={product.available ? "good" : "warn"} /></td></tr>)}
          </tbody></table></div>
        </section>

        <section className="grid two">
          <article className="panel" id="new-order"><h2>جریان quote و checkout</h2><ol>{portal.quoteFlow.map((step) => <li key={step}>{step}</li>)}</ol><p className="notice">پرداخت PREPAID یا CREDIT یک سفارش و دقیقاً یک اثر مالی دفترکل ایجاد می‌کند؛ کیف پول مشتری ذی‌نفع شارژ نمی‌شود.</p></article>
          <article className="panel" id="customers"><h2>مشتریان مدیریت‌شده</h2>{portal.customerRows.map((customer) => <div className="row-card" key={customer.reference}><strong>{customer.label}</strong><span dir="ltr">{customer.reference}</span><small>{customer.state} · {customer.invitation}</small></div>)}<p>توکن‌ها، نشست‌ها، initData تلگرام، یادداشت‌های مدیر و پرداخت‌های مستقیم مشتری هرگز نمایش داده نمی‌شوند.</p></article>
        </section>

        <section className="grid two">
          <article className="panel" id="orders"><h2>سفارش‌ها و توضیح READY_FOR_FULFILLMENT</h2>{portal.orderRows.map((order) => <div className="row-card" key={order.reference}><strong dir="ltr">{order.reference}</strong><span>{order.customerLabel} · <Money amount={order.wholesaleRial} /></span><small>{order.fulfillmentState}: پرداخت کامل است، اما ساخت سرویس و لینک/QR/کانفیگ در این milestone وجود ندارد.</small></div>)}</article>
          <article className="panel" id="wallet"><h2>کیف پول، رزرو و اعتبار</h2><ul><li>مانده posted، available و reserved فقط خواندنی است.</li><li>تاریخچه تراکنش‌ها از ledger-backed API صفحه‌بندی می‌شود.</li><li>ویرایش مانده یا سقف اعتبار در رابط فروشنده وجود ندارد.</li><li>همزمانی checkout نمی‌تواند از سقف اعتبار عبور کند.</li></ul></article>
        </section>

        <section className="grid two">
          <article className="panel" id="remarks"><h2>Remark template امن</h2><code dir="ltr">{portal.remark.template}</code><p>{remarkValidation.ok ? "قالب معتبر است و preview با داده مصنوعی نمایش داده می‌شود." : remarkValidation.reason}</p><ul>{portal.remark.allowedPlaceholders.map((placeholder) => <li key={placeholder} dir="ltr">{placeholder}</li>)}</ul></article>
          <article className="panel" id="brand"><h2>برندینگ و white-label محدود</h2><p>{brandingValidation.ok ? "پیش‌نویس برند از schema امن عبور کرده است." : brandingValidation.reason}</p><dl><dt>نام نمایشی</dt><dd>{portal.brandingDraft.displayBrand}</dd><dt>رنگ accent</dt><dd dir="ltr">{portal.brandingDraft.accentColor}</dd><dt>مرزها</dt><dd>بدون CSS دلخواه، JavaScript، HTML خام، فونت خارجی یا callback ناامن.</dd></dl></article>
        </section>

        <section className="panel" id="security"><h2>امنیت، ذخیره‌سازی و فعالیت</h2><div className="grid three">{storagePolicyChecklist.map((item) => <div className="check" key={item}>✓ {item}</div>)}</div><div className="activity">{portal.activity.map((event) => <p key={event.reference}><span dir="ltr">{event.reference}</span> — {event.label}</p>)}</div></section>
      </section>
    </main>
  );
}
