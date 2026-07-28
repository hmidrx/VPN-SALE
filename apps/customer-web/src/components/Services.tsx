"use client";

import React from "react";
import {
  getService,
  getOperationEligibility,
  listServices,
  type ServiceDetail,
  type ServiceSummary,
} from "../services";
import {
  calculateTimeMetric,
  clampPercentage,
  formatBytes,
} from "../service-metrics";
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

function SyncIcon() {
  return (
    <svg className="metric-sync-icon" aria-hidden="true" viewBox="0 0 24 24">
      <path d="M20 7v5h-5M4 17v-5h5M6.2 9a7 7 0 0 1 11.4-2L20 12M4 12l2.4 5a7 7 0 0 0 11.4-2" />
    </svg>
  );
}
function MetricRing({
  label,
  value,
  supporting,
  percentage,
  unavailable = false,
  unlimited = false,
}: {
  label: string;
  value: string;
  supporting: string;
  percentage: number | null;
  unavailable?: boolean;
  unlimited?: boolean;
}) {
  const safe = percentage === null ? null : clampPercentage(percentage);
  return (
    <div
      className={`metric-ring ${unavailable ? "is-unavailable" : ""}`}
      role={safe === null ? undefined : "progressbar"}
      aria-label={
        unavailable && supporting.startsWith("حجم کل")
          ? `اطلاعات مصرف همگام نشده است؛ ${supporting.replace("حجم کل", "حجم کل سرویس")} است.`
          : `${label}: ${value}. ${supporting}`
      }
      aria-valuemin={safe === null ? undefined : 0}
      aria-valuemax={safe === null ? undefined : 100}
      aria-valuenow={safe === null ? undefined : Math.round(safe)}
      style={{ "--metric-progress": safe ?? 0 } as React.CSSProperties}
    >
      <svg aria-hidden="true" viewBox="0 0 100 100">
        <circle className="metric-track" cx="50" cy="50" r="42" />
        <circle
          className="metric-value"
          cx="50"
          cy="50"
          r="42"
          pathLength="100"
        />
      </svg>
      <span>
        {unavailable && <SyncIcon />}
        <small>{label}</small>
        <strong>{unlimited ? "∞" : value}</strong>
        <small>{supporting}</small>
      </span>
    </div>
  );
}
function CopyReferenceButton({
  value,
  compact = false,
}: {
  value: string;
  compact?: boolean;
}) {
  const [copied, setCopied] = React.useState(false);
  React.useEffect(() => () => undefined, []);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };
  return (
    <button
      className="copy-reference"
      type="button"
      onClick={() => void copy()}
      aria-label="کپی شناسه عمومی سرویس"
    >
      <code dir="ltr">{compact ? shortRef(value) : value}</code>
      <span aria-live="polite">{copied ? "کپی شد" : "کپی"}</span>
    </button>
  );
}
function ServiceMetrics({ service: s }: { service: ServiceSummary }) {
  const time = calculateTimeMetric(s.starts_at, s.expires_at);
  const usage = s.usage,
    quota = s.entitlement.traffic_quota_bytes;
  const usedPercent =
    usage && usage.total_bytes
      ? (usage.used_bytes / usage.total_bytes) * 100
      : null;
  return (
    <div className="service-metrics">
      <MetricRing
        label="زمان باقی‌مانده"
        value={
          time.remainingDays === null
            ? "نامشخص"
            : `${time.remainingDays.toLocaleString("fa-IR")} روز`
        }
        supporting={
          s.entitlement.duration_days
            ? `از ${s.entitlement.duration_days.toLocaleString("fa-IR")} روز`
            : "مدت سرویس"
        }
        percentage={time.percentage}
        unavailable={time.percentage === null && !time.unlimited}
        unlimited={time.unlimited}
      />
      <MetricRing
        label="مصرف ترافیک"
        value={
          usage
            ? formatBytes(usage.used_bytes)
            : quota
              ? "همگام نشده"
              : "نامشخص"
        }
        supporting={quota ? `حجم کل ${formatBytes(quota)}` : "حجم نامشخص"}
        percentage={usedPercent}
        unavailable={!usage}
        unlimited={usage?.unlimited}
      />
    </div>
  );
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
      <ServiceMetrics service={s} />
      <dl className="service-info-grid">
        <div>
          <dt>انقضا</dt>
          <dd>{faDate(s.expires_at)}</dd>
        </div>
        <div>
          <dt>موقعیت</dt>
          <dd>{s.entitlement.location_label ?? "ثبت نشده"}</dd>
        </div>
        <div>
          <dt>دستگاه</dt>
          <dd>
            {s.entitlement.device_limit === null
              ? "ثبت نشده"
              : `${s.entitlement.device_limit.toLocaleString("fa-IR")} دستگاه`}
          </dd>
        </div>
        <div>
          <dt>وضعیت اتصال</dt>
          <dd>{s.delivery_ready ? "آماده اتصال" : "هنوز آماده نیست"}</dd>
        </div>
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
    [error, setError] = React.useState(false),
    [refreshing, setRefreshing] = React.useState(false),
    [refreshMessage, setRefreshMessage] = React.useState(""),
    [tab, setTab] = React.useState<(typeof tabs)[number][0]>("overview");
  React.useEffect(() => {
    const controller = new AbortController();
    void getOperationEligibility(serviceReference, controller.signal)
      .then((operations) => {
        setData((current) =>
          current ? { ...current, eligible_operations: operations } : current,
        );
      })
      .catch((caught) => {
        if ((caught as Error).name !== "AbortError") return;
      });
    return () => controller.abort();
  }, [serviceReference]);
  const load = React.useCallback(() => {
    const c = new AbortController();
    setError(false);
    setRefreshing(true);
    void getService(serviceReference, c.signal)
      .then((next) => {
        setData(next);
        setRefreshMessage("اطلاعات سرویس به‌روز شد");
        window.setTimeout(() => setRefreshMessage(""), 2200);
      })
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setError(true);
      })
      .finally(() => setRefreshing(false));
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
    st = serviceStatus(s.lifecycle);
  const selectTab = (next: (typeof tabs)[number][0], focus = false) => {
    setTab(next);
    requestAnimationFrame(() => {
      const element = document.getElementById(`service-tab-${next}`);
      element?.scrollIntoView({
        behavior: "smooth",
        inline: "center",
        block: "nearest",
      });
      if (focus) element?.focus();
    });
  };
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
        <span className={`status tone-${st.tone}`}>{st.label}</span>
        <button
          className="detail-refresh"
          onClick={load}
          disabled={refreshing}
          aria-label={refreshing ? "در حال تازه‌سازی سرویس" : "تازه‌سازی سرویس"}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24">
            <path d="M20 7v5h-5M4 17v-5h5M6.2 9a7 7 0 0 1 11.4-2L20 12M4 12l2.4 5a7 7 0 0 0 11.4-2" />
          </svg>
        </button>
        <span className="sr-only" aria-live="polite">
          {refreshMessage}
        </span>
      </header>
      <nav className="service-tabs" role="tablist" aria-label="بخش‌های سرویس">
        {tabs.map(([v, l]) => (
          <button
            role="tab"
            id={`service-tab-${v}`}
            aria-controls={`service-panel-${v}`}
            aria-selected={tab === v}
            tabIndex={tab === v ? 0 : -1}
            onClick={() => selectTab(v)}
            onKeyDown={(event) => {
              const index = tabs.findIndex(([key]) => key === v);
              let next: (typeof tabs)[number][0] | null = null;
              if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                const direction = event.key === "ArrowLeft" ? 1 : -1;
                next = tabs[(index + direction + tabs.length) % tabs.length][0];
              } else if (event.key === "Home") next = tabs[0][0];
              else if (event.key === "End") next = tabs[tabs.length - 1][0];
              if (next) {
                event.preventDefault();
                selectTab(next, true);
              }
            }}
            key={v}
          >
            {l}
          </button>
        ))}
      </nav>
      {tab === "overview" && (
        <div
          className="detail-grid"
          role="tabpanel"
          id="service-panel-overview"
          aria-labelledby="service-tab-overview"
        >
          <article className="service-hero">
            <p>{st.description}</p>
            <CopyReferenceButton value={s.service_reference} compact />
            <ServiceMetrics service={s} />
            <dl className="service-info-grid overview-info">
              <div>
                <dt>تاریخ فعال‌سازی</dt>
                <dd>{faDate(s.activated_at)}</dd>
              </div>
              <div>
                <dt>تاریخ انقضا</dt>
                <dd>{faDate(s.expires_at)}</dd>
              </div>
              <div>
                <dt>موقعیت</dt>
                <dd>{s.entitlement.location_label ?? "ثبت نشده"}</dd>
              </div>
              <div>
                <dt>کیفیت</dt>
                <dd>{s.entitlement.quality_label ?? "ثبت نشده"}</dd>
              </div>
              <div>
                <dt>تعداد دستگاه</dt>
                <dd>
                  {s.entitlement.device_limit === null
                    ? "ثبت نشده"
                    : `${s.entitlement.device_limit.toLocaleString("fa-IR")} دستگاه`}
                </dd>
              </div>
              <div>
                <dt>وضعیت اتصال</dt>
                <dd>{s.delivery_ready ? "آماده اتصال" : "هنوز آماده نیست"}</dd>
              </div>
            </dl>
          </article>
          <Actions data={data} />
        </div>
      )}
      {tab === "connection" && (
        <article
          className="detail-panel compact-state"
          role="tabpanel"
          id="service-panel-connection"
          aria-labelledby="service-tab-connection"
        >
          {!data.delivery.ready ? (
            <>
              <h3>اطلاعات اتصال هنوز آماده نشده است</h3>
              <p>
                سرویس همچنان در حال آماده‌سازی است. تا دریافت تحویل معتبر، لینک
                اشتراک یا QR نمایش داده نمی‌شود.
              </p>
              <div className="panel-actions">
                <button onClick={load} disabled={refreshing}>
                  بررسی دوباره
                </button>
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
        <article
          className="detail-panel"
          role="tabpanel"
          id="service-panel-usage"
          aria-labelledby="service-tab-usage"
        >
          <h2>مصرف سرویس</h2>
          {data.summary.usage === null ? (
            <div className="usage-unavailable">
              <MetricRing
                label="مصرف ترافیک"
                value={
                  data.summary.entitlement.traffic_quota_bytes
                    ? "همگام نشده"
                    : "نامشخص"
                }
                supporting={
                  data.summary.entitlement.traffic_quota_bytes
                    ? `حجم کل ${formatBytes(data.summary.entitlement.traffic_quota_bytes)}`
                    : "حجم نامشخص"
                }
                percentage={null}
                unavailable
              />
              <p>مقدار مصرف هنوز از سرور همگام نشده است.</p>
              <small>این وضعیت به معنی مصرف صفر نیست.</small>
              <div className="panel-actions">
                <button onClick={load}>تازه‌سازی</button>
                <a href="/support">پشتیبانی</a>
              </div>
            </div>
          ) : (
            <UsageDetails service={s} />
          )}
        </article>
      )}
      {tab === "manage" && <Actions data={data} expanded />}
      {tab === "activity" && (
        <article
          className="detail-panel compact-state"
          role="tabpanel"
          id="service-panel-activity"
          aria-labelledby="service-tab-activity"
        >
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
            <>
              <h3>فعالیتی برای نمایش وجود ندارد</h3>
              <p>هنوز فعالیت معتبری برای این سرویس ثبت نشده است.</p>
            </>
          )}
        </article>
      )}
    </section>
  );
}
function UsageDetails({ service }: { service: ServiceSummary }) {
  const usage = service.usage;
  if (!usage) return null;
  const total = usage.total_bytes ?? service.entitlement.traffic_quota_bytes;
  const percentage = total
    ? clampPercentage((usage.used_bytes / total) * 100)
    : null;
  return (
    <div className="usage-details">
      <MetricRing
        label="درصد مصرف‌شده"
        value={formatBytes(usage.remaining_bytes, usage.unlimited)}
        supporting={total ? `حجم کل ${formatBytes(total)}` : "حجم نامشخص"}
        percentage={percentage}
        unlimited={usage.unlimited}
      />
      {usage.stale && (
        <span className="usage-stale">اطلاعات نیازمند تازه‌سازی است</span>
      )}
      <dl className="service-info-grid">
        <div>
          <dt>مصرف‌شده</dt>
          <dd>{formatBytes(usage.used_bytes)}</dd>
        </div>
        <div>
          <dt>باقی‌مانده</dt>
          <dd>{formatBytes(usage.remaining_bytes, usage.unlimited)}</dd>
        </div>
        <div>
          <dt>حجم کل</dt>
          <dd>{formatBytes(total, usage.unlimited)}</dd>
        </div>
        <div>
          <dt>درصد مصرف</dt>
          <dd>
            {percentage === null
              ? "ثبت نشده"
              : `${Math.round(percentage).toLocaleString("fa-IR")}٪`}
          </dd>
        </div>
        <div className="full-cell">
          <dt>آخرین همگام‌سازی</dt>
          <dd>{faDate(usage.last_synced_at)}</dd>
        </div>
      </dl>
    </div>
  );
}
function Actions({
  data,
  expanded = false,
}: {
  data: ServiceDetail;
  expanded?: boolean;
}) {
  const commercial = data.eligible_operations.filter(
    (operation) => operation.billable,
  );
  const maintenance = data.eligible_operations.filter(
    (operation) => !operation.billable,
  );
  if (!expanded) {
    const eligible = maintenance
      .filter((operation) => operation.eligible)
      .slice(0, 2);
    return (
      <article className="detail-panel recommended-actions">
        <h2>اقدام‌های پیشنهادی</h2>
        <div className="operation-grid">
          {eligible.map((operation) => (
            <button key={operation.operation_type}>
              {operationLabels[operation.operation_type] ?? "بررسی سرویس"}
              <small>آماده انجام</small>
            </button>
          ))}
          <a href="/support">
            پشتیبانی<small>گفت‌وگو با تیم پشتیبانی</small>
          </a>
        </div>
      </article>
    );
  }
  const rows = (operations: typeof maintenance) =>
    operations.map((operation) => (
      <button
        key={operation.operation_type}
        disabled={!operation.eligible || operation.billable}
      >
        {operationLabels[operation.operation_type] ?? "در حال بررسی"}
        <small>
          {operation.eligible && !operation.billable
            ? "آماده انجام"
            : "در دسترس نیست"}
        </small>
      </button>
    ));
  return (
    <article
      className="detail-panel management-panel"
      role="tabpanel"
      id="service-panel-manage"
      aria-labelledby="service-tab-manage"
    >
      <h2>مدیریت سرویس</h2>
      <section>
        <h3>خرید و تمدید</h3>
        <p className="operation-banner">
          قیمت‌گذاری عملیات خرید و تمدید هنوز فعال نشده است.
        </p>
        <div className="operation-grid">{rows(commercial)}</div>
      </section>
      <section>
        <h3>اتصال و نگهداری</h3>
        <div className="operation-grid">{rows(maintenance)}</div>
      </section>
      <section>
        <h3>وضعیت سرویس</h3>
        <div className="operation-grid">
          <a href="/support">
            پشتیبانی<small>گفت‌وگو با تیم پشتیبانی</small>
          </a>
        </div>
      </section>
    </article>
  );
}
