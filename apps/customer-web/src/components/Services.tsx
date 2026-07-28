"use client";

import React from "react";
import {
  getService,
  getOperationEligibility,
  listServices,
  type ServiceDetail,
  type ServiceSummary,
} from "../services";
import { calculateTimeMetric, clampPercentage, formatBytes } from "../service-metrics";
import { operationLabels, serviceStatus } from "../service-status";

const filters = [
  ["all", "همه"],
  ["active", "فعال"],
  ["provisioning", "در حال آماده‌سازی"],
  ["suspended", "متوقف"],
  ["expired", "منقضی"],
] as const;

const faDate = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium" }).format(
        new Date(value),
      )
    : "ثبت نشده";
const shortRef = (value: string) =>
  value.length > 12 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value;
function remaining(value: string | null) {
  if (!value) return null;
  return Math.max(
    0,
    Math.ceil((new Date(value).getTime() - Date.now()) / 86400000),
  );
}
function refreshLabel(value: Date | null): string {
  if (!value) return "هنوز به‌روزرسانی نشده";
  return `آخرین به‌روزرسانی: ${new Intl.DateTimeFormat("fa-IR", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(value)}`;
}

export function ServicesPage(): React.ReactElement {
  const [items, setItems] = React.useState<ServiceSummary[] | null>(null);
  const [error, setError] = React.useState(false);
  const [filter, setFilter] = React.useState("all");
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState("newest");
  const [refreshed, setRefreshed] = React.useState<Date | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const fetchItems = React.useCallback(async (signal?: AbortSignal) => {
    setError(false);
    try {
      const next = await listServices(signal);
      setItems(next);
      setRefreshed(new Date());
    } catch (caught) {
      if ((caught as Error).name !== "AbortError") setError(true);
    }
  }, []);

  React.useEffect(() => {
    const controller = new AbortController();
    void fetchItems(controller.signal);
    return () => controller.abort();
  }, [fetchItems]);

  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    await fetchItems();
    setRefreshing(false);
  };

  const shown = [...(items ?? [])].filter((item) => {
    const status = serviceStatus(item.lifecycle);
    return (
      (filter === "all" || status.group === filter) &&
      (item.display_name.includes(query) ||
        shortRef(item.service_reference)
          .toLowerCase()
          .includes(query.toLowerCase()))
    );
  });
  shown.sort((a, b) =>
    sort === "expiry"
      ? (a.expires_at ? Date.parse(a.expires_at) : Infinity) -
        (b.expires_at ? Date.parse(b.expires_at) : Infinity)
      : sort === "active"
        ? Number(serviceStatus(b.lifecycle).group === "active") -
          Number(serviceStatus(a.lifecycle).group === "active")
        : Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const count = items?.length ?? 0;

  return (
    <section className="services-page">
      <header className="services-header">
        <div>
          <span>مرکز خدمات مشتریان</span>
          <h1>سرویس‌های من</h1>
          <p>وضعیت و دسترسی امن سرویس‌های خود را یک‌جا مدیریت کنید.</p>
        </div>
        {count > 0 && (
          <a className="ui-button services-purchase" href="/catalog/products">
            خرید سرویس جدید
          </a>
        )}
      </header>
      <div className="services-meta" aria-live="polite">
        <strong>{count.toLocaleString("fa-IR")} سرویس</strong>
        <span>{refreshLabel(refreshed)}</span>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
          aria-label={
            refreshing ? "در حال تازه‌سازی سرویس‌ها" : "تازه‌سازی سرویس‌ها"
          }
        >
          <svg aria-hidden="true" viewBox="0 0 24 24">
            <path d="M20 7v5h-5M4 17v-5h5M6.1 9a7 7 0 0 1 11.5-2L20 12M4 12l2.4 5a7 7 0 0 0 11.5-2" />
          </svg>
          <span>{refreshing ? "در حال تازه‌سازی" : "تازه‌سازی"}</span>
        </button>
      </div>
      <div className="services-toolbar">
        <label className="services-search">
          <span className="sr-only">جستجوی سرویس</span>
          <svg aria-hidden="true" viewBox="0 0 24 24">
            <circle cx="11" cy="11" r="6" />
            <path d="m16 16 4 4" />
          </svg>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="جستجو با نام یا شناسه کوتاه"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="پاک‌کردن جستجو"
            >
              پاک‌کردن
            </button>
          )}
        </label>
        <label className="services-sort">
          <span className="sr-only">مرتب‌سازی سرویس‌ها</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            <option value="newest">جدیدترین</option>
            <option value="expiry">نزدیک‌ترین انقضا</option>
            <option value="active">ابتدا فعال‌ها</option>
          </select>
          <svg aria-hidden="true" viewBox="0 0 20 20">
            <path d="m6 8 4 4 4-4" />
          </svg>
        </label>
        <div className="service-filters" aria-label="فیلتر وضعیت">
          {filters.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {items === null && !error ? (
        <div className="service-grid" aria-label="در حال بارگذاری">
          <i />
          <i />
          <i />
        </div>
      ) : error ? (
        <div className="services-notice">
          <h2>دریافت سرویس‌ها ممکن نشد</h2>
          <p>
            اطلاعات قبلی تغییر نکرده است. اتصال را بررسی و دوباره تلاش کنید.
          </p>
          <button type="button" onClick={() => void refresh()}>
            تلاش دوباره
          </button>
        </div>
      ) : items?.length === 0 ? (
        <Empty />
      ) : shown.length === 0 ? (
        <div className="services-notice">
          <h2>سرویسی با این مشخصات پیدا نشد</h2>
          <button
            type="button"
            onClick={() => {
              setFilter("all");
              setQuery("");
            }}
          >
            پاک‌کردن فیلترها
          </button>
        </div>
      ) : (
        <div className="service-grid">
          {shown.map((item) => (
            <ServiceCard key={item.service_reference} service={item} />
          ))}
        </div>
      )}
    </section>
  );
}

function Empty() {
  return (
    <article className="services-empty">
      <svg aria-hidden="true" viewBox="0 0 120 100">
        <path d="M60 8 103 29v28c0 22-16 34-43 43C33 91 17 79 17 57V29L60 8Z" />
        <path d="m42 54 12 12 25-29" />
      </svg>
      <h2>هنوز سرویسی ندارید</h2>
      <p>پس از انتخاب و خرید پلن، سرویس شما در این بخش نمایش داده می‌شود.</p>
      <div>
        <a className="ui-button" href="/catalog/products">
          مشاهده پلن‌ها
        </a>
        <a href="/education">راهنمای انتخاب سرویس</a>
      </div>
    </article>
  );
}

function MetricRing({ label, value, supporting, percentage, unavailable = false, unlimited = false }: { label: string; value: string; supporting: string; percentage: number | null; unavailable?: boolean; unlimited?: boolean }) {
  const safe = percentage === null ? null : clampPercentage(percentage);
  return <div className={`metric-ring ${unavailable ? "is-unavailable" : ""}`} role={safe === null ? undefined : "progressbar"} aria-label={`${label}: ${value}. ${supporting}`} aria-valuemin={safe === null ? undefined : 0} aria-valuemax={safe === null ? undefined : 100} aria-valuenow={safe === null ? undefined : Math.round(safe)} style={{ "--metric-progress": safe ?? 0 } as React.CSSProperties}>
    <svg aria-hidden="true" viewBox="0 0 100 100"><circle className="metric-track" cx="50" cy="50" r="42"/><circle className="metric-value" cx="50" cy="50" r="42" pathLength="100"/></svg>
    <span><small>{label}</small><strong>{unlimited ? "∞" : value}</strong><small>{supporting}</small></span>
  </div>;
}
function CopyReferenceButton({ value, compact = false }: { value: string; compact?: boolean }) {
  const [copied, setCopied] = React.useState(false);
  React.useEffect(() => () => undefined, []);
  const copy = async () => { await navigator.clipboard.writeText(value); setCopied(true); window.setTimeout(() => setCopied(false), 1800); };
  return <button className="copy-reference" type="button" onClick={() => void copy()} aria-label="کپی شناسه عمومی سرویس"><code dir="ltr">{compact ? shortRef(value) : value}</code><span aria-live="polite">{copied ? "کپی شد" : "کپی"}</span></button>;
}
function ServiceMetrics({ service: s }: { service: ServiceSummary }) {
  const time = calculateTimeMetric(s.starts_at, s.expires_at);
  const usage = s.usage, quota = s.entitlement.traffic_quota_bytes;
  const usedPercent = usage && usage.total_bytes ? usage.used_bytes / usage.total_bytes * 100 : null;
  return <div className="service-metrics">
    <MetricRing label="زمان باقی‌مانده" value={time.remainingDays === null ? "نامشخص" : `${time.remainingDays.toLocaleString("fa-IR")} روز`} supporting={s.entitlement.duration_days ? `از ${s.entitlement.duration_days.toLocaleString("fa-IR")} روز` : "مدت سرویس"} percentage={time.percentage} unavailable={time.percentage === null && !time.unlimited} unlimited={time.unlimited}/>
    <MetricRing label="مصرف ترافیک" value={usage ? formatBytes(usage.used_bytes) : quota ? "همگام نشده" : "نامشخص"} supporting={quota ? `حجم کل ${formatBytes(quota)}` : "حجم نامشخص"} percentage={usedPercent} unavailable={!usage} unlimited={usage?.unlimited}/>
  </div>;
}
function ServiceCard({ service: s }: { service: ServiceSummary }) {
  const st = serviceStatus(s.lifecycle);
  return (
    <article className={`service-card tone-${st.tone}`}>
      <header>
        <div>
          <span>{st.label}</span>
          <h2>{s.display_name}</h2>
        </div>
        <CopyReferenceButton value={s.service_reference} compact />
      </header>
      <p>{st.description}</p>
      <ServiceMetrics service={s}/><dl className="service-info-grid">
        <div>
          <dt>{s.activated_at ? "فعال‌سازی" : "ثبت سفارش"}</dt>
          <dd>{faDate(s.activated_at ?? s.created_at)}</dd>
        </div>
        {s.expires_at && (
          <div>
            <dt>انقضا</dt>
            <dd>
              {faDate(s.expires_at)}
            </dd>
          </div>
        )}
        <div>
          <dt>اطلاعات اتصال</dt>
          <dd>{s.delivery_ready ? "آماده" : "هنوز آماده نیست"}</dd>
        </div>
        {s.entitlement.location_label && <div><dt>موقعیت</dt><dd>{s.entitlement.location_label}</dd></div>}
        {s.entitlement.device_limit !== null && <div><dt>دستگاه</dt><dd>{s.entitlement.device_limit.toLocaleString("fa-IR")}</dd></div>}
      </dl>
      {st.group === "provisioning" && (
        <div className="service-progress">
          <div>
            <span>پیشرفت آماده‌سازی</span>
            <b>{s.provisioning_progress}٪</b>
          </div>
          <progress max="100" value={s.provisioning_progress} />
        </div>
      )}
      <a
        className="service-manage"
        href={`/services/${encodeURIComponent(s.service_reference)}`}
      >
        مدیریت سرویس <span>←</span>
      </a>
    </article>
  );
}
const tabs = [
  ["overview", "نمای کلی"],
  ["connection", "اتصال"],
  ["usage", "مصرف"],
  ["manage", "مدیریت"],
  ["activity", "فعالیت‌ها"],
] as const;
export function ServiceDetailPage({
  serviceReference,
}: {
  serviceReference: string;
}): React.ReactElement {
  const [data, setData] = React.useState<ServiceDetail | null>(null),
    [error, setError] = React.useState(false), [refreshing, setRefreshing] = React.useState(false),
    [tab, setTab] = React.useState<(typeof tabs)[number][0]>("overview");
  React.useEffect(() => {
    const controller = new AbortController();
    void getOperationEligibility(serviceReference, controller.signal).then((operations) => {
      setData((current) => current ? { ...current, eligible_operations: operations } : current);
    }).catch((caught) => { if ((caught as Error).name !== "AbortError") return; });
    return () => controller.abort();
  }, [serviceReference]);
  const load = React.useCallback(() => {
    const c = new AbortController();
    setError(false);
    setRefreshing(true); void getService(serviceReference, c.signal)
      .then(setData)
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setError(true);
      }).finally(() => setRefreshing(false));
    return () => c.abort();
  }, [serviceReference]);
  React.useEffect(load, [load]);
  if (error)
    return (
      <section className="services-notice">
        <h1>دریافت سرویس ممکن نشد</h1>
        <a href="/services">بازگشت به سرویس‌ها</a>
        <button onClick={load}>تلاش دوباره</button>
      </section>
    );
  if (!data)
    return (
      <div className="service-detail-loading" aria-label="در حال بارگذاری" />
    );
  const s = data.summary,
    st = serviceStatus(s.lifecycle),
    days = remaining(s.expires_at);
  return (
    <section className="service-detail">
      <header className="detail-top">
        <a href="/services" aria-label="بازگشت به سرویس‌ها">
          →
        </a>
        <div>
          <small>مدیریت سرویس</small>
          <h1>{s.display_name}</h1>
        </div>
        <span className={`status tone-${st.tone}`}>{st.label}</span><button onClick={load} disabled={refreshing}>{refreshing ? "در حال تازه‌سازی" : "تازه‌سازی"}</button>
      </header>
      <nav className="service-tabs" role="tablist" aria-label="بخش‌های سرویس">
        {tabs.map(([v, l]) => (
          <button
            role="tab"
            id={`service-tab-${v}`} aria-controls={`service-panel-${v}`}
            aria-selected={tab === v}
            tabIndex={tab === v ? 0 : -1}
            onClick={(event) => { setTab(v); event.currentTarget.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" }); }}
            onKeyDown={(event) => { const index = tabs.findIndex(([key]) => key === v); if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); const direction = event.key === "ArrowLeft" ? 1 : -1; const next = tabs[(index + direction + tabs.length) % tabs.length][0]; setTab(next); document.getElementById(`service-tab-${next}`)?.focus(); } }}
            key={v}
          >
            {l}
          </button>
        ))}
      </nav>
      {tab === "overview" && (
        <div className="detail-grid" role="tabpanel" id="service-panel-overview" aria-labelledby="service-tab-overview">
          <article className="service-hero">
            <p>{st.description}</p>
            <CopyReferenceButton value={s.service_reference}/>
            <ServiceMetrics service={s}/>
            <dl>
              <div>
                <dt>شناسه عمومی</dt>
                <dd>
                  <code>{shortRef(s.service_reference)}</code>{" "}
                  <button
                    onClick={() =>
                      void navigator.clipboard.writeText(s.service_reference)
                    }
                  >
                    کپی
                  </button>
                </dd>
              </div>
              <div>
                <dt>سلامت سرویس</dt>
                <dd>{data.service_health}</dd>
              </div>
              <div>
                <dt>فعال‌سازی</dt>
                <dd>{faDate(s.activated_at)}</dd>
              </div>
              <div>
                <dt>انقضا</dt>
                <dd>
                  {faDate(s.expires_at)} {days !== null && `(${days} روز)`}
                </dd>
              </div>
              {data.summary.entitlement.device_limit !== null && (
                <div>
                  <dt>تعداد دستگاه</dt>
                  <dd>{data.summary.entitlement.device_limit}</dd>
                </div>
              )}
            </dl>
          </article>
          <Actions data={data} />
        </div>
      )}
      {tab === "connection" && (
        <article className="detail-panel">
          <h2>مرکز اتصال</h2>
          {!data.delivery.ready ? (
            <>
              <h3>اطلاعات اتصال هنوز آماده نشده است</h3>
              <p>
                سرویس همچنان در حال آماده‌سازی است. تا دریافت تحویل معتبر، لینک
                اشتراک یا QR نمایش داده نمی‌شود.
              </p>
              <div className="panel-actions">
                <button onClick={load}>بررسی دوباره</button>
                <a href="/support">پشتیبانی</a>
              </div>
            </>
          ) : (
            <p>
              فرمت‌های تحویل معتبر پس از دریافت امن از سرور اینجا نمایش داده
              می‌شوند.
            </p>
          )}
        </article>
      )}
      {tab === "usage" && (
        <article className="detail-panel" role="tabpanel" id="service-panel-usage" aria-labelledby="service-tab-usage">
          <h2>مصرف سرویس</h2>
          {data.summary.usage === null ? (
            <div className="usage-unavailable"><MetricRing label="مصرف ترافیک" value={data.summary.entitlement.traffic_quota_bytes ? "همگام نشده" : "نامشخص"} supporting={data.summary.entitlement.traffic_quota_bytes ? `حجم کل ${formatBytes(data.summary.entitlement.traffic_quota_bytes)}` : "حجم نامشخص"} percentage={null} unavailable/><p>مقدار مصرف هنوز از سرور همگام نشده است.</p><small>این وضعیت به معنی مصرف صفر نیست.</small><div className="panel-actions"><button onClick={load}>تازه‌سازی</button><a href="/support">پشتیبانی</a></div></div>
          ) : null}
        </article>
      )}
      {tab === "manage" && <Actions data={data} expanded />}
      {tab === "activity" && (
        <article className="detail-panel">
          <h2>فعالیت‌ها</h2>
          {data.latest_activity.length ? (
            <ol className="timeline">
              {data.latest_activity.map((x, i) => (
                <li key={`${x.event}-${i}`}>
                  <strong>{x.label}</strong>
                  <time>{faDate(x.occurred_at)}</time>
                </li>
              ))}
            </ol>
          ) : (
            <p>فعالیت تازه‌ای برای نمایش وجود ندارد.</p>
          )}
        </article>
      )}
    </section>
  );
}
function Actions({
  data,
  expanded = false,
}: {
  data: ServiceDetail;
  expanded?: boolean;
}) {
  return (
    <article className="detail-panel">
      <h2>{expanded ? "مدیریت سرویس" : "اقدام‌های پیشنهادی"}</h2>
      <div className="operation-grid">
        {data.eligible_operations.map((x) => (
          <button
            key={x.operation_type}
            disabled={!x.eligible || x.billable}
            title={
              x.billable
                ? "قیمت‌گذاری این عملیات هنوز فعال نشده است"
                : undefined
            }
          >
            {operationLabels[x.operation_type] ?? "در حال بررسی"}
            <small>
              {x.billable
                ? "قیمت‌گذاری هنوز فعال نیست"
                : x.eligible
                  ? "آماده انجام"
                  : "در دسترس نیست"}
            </small>
          </button>
        ))}
        <a href="/support">
          پشتیبانی<small>گفت‌وگو با تیم پشتیبانی</small>
        </a>
      </div>
    </article>
  );
}
