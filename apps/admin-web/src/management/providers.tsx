"use client";

import React from "react";

import { EmptyState, StatusBadge, Tech } from "../components/ManagementShell";
import {
  ProviderApiError,
  providerApi,
  type ProviderCapability,
  type ProviderInbound,
  type ProviderPanel,
} from "./providers-api";

export const providerPermissions = {
  read: "providers.read",
  manage: "providers.manage",
  credentials: "providers.manage_credentials",
  test: "providers.test_connection",
  sync: "providers.sync",
  inventory: "providers.read_inventory",
  diagnostics: "providers.read_diagnostics",
} as const;

const statusFa: Record<string, string> = {
  DRAFT: "پیش‌نویس",
  ACTIVE: "فعال و تأییدشده",
  DISABLED: "غیرفعال",
  RECERTIFICATION_REQUIRED: "نیازمند تأیید مجدد",
  CONTRACT_VERIFIED: "قرارداد تأیید شد",
  VERSION_UNSUPPORTED: "نسخه پشتیبانی نمی‌شود",
  SUCCESS: "موفق",
  FAILED: "ناموفق",
};

function messageOf(error: unknown): string {
  if (!(error instanceof ProviderApiError)) return "ارتباط با سرور مدیریت برقرار نشد.";
  const messages: Record<string, string> = {
    PROVIDER_ENDPOINT_REJECTED: "آدرس پنل یا سیاست شبکه امن نیست.",
    PROVIDER_VERSION_UNSUPPORTED: "فقط قرارداد رسمی 3x-ui نسخه 3.7.0 فعال است.",
    PROVIDER_CREDENTIAL_VAULT_UNAVAILABLE: "کلید امن Vault روی سرور تنظیم نشده است.",
    CONCURRENT_MODIFICATION: "اطلاعات هم‌زمان تغییر کرده؛ صفحه را تازه کنید.",
  };
  return messages[error.code] ?? `عملیات انجام نشد (${error.code}).`;
}

function usePanels(): {
  panels: ProviderPanel[];
  loading: boolean;
  error: string;
  reload: () => void;
} {
  const [panels, setPanels] = React.useState<ProviderPanel[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [revision, setRevision] = React.useState(0);
  React.useEffect(() => {
    let active = true;
    setLoading(true);
    void providerApi
      .panels()
      .then((value) => {
        if (active) {
          setPanels(value.items);
          setError("");
        }
      })
      .catch((reason: unknown) => active && setError(messageOf(reason)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [revision]);
  return { panels, loading, error, reload: () => setRevision((value) => value + 1) };
}

export function ProviderDashboard(): React.ReactElement {
  const { panels, loading, error, reload } = usePanels();
  const active = panels.filter((panel) => panel.status === "ACTIVE").length;
  const needsAttention = panels.filter((panel) =>
    ["RECERTIFICATION_REQUIRED", "DISABLED"].includes(panel.status),
  ).length;
  const inboundReady = panels.filter(
    (panel) => panel.last_connection_test?.status === "CONTRACT_VERIFIED",
  ).length;
  return (
    <section className="panel stack" dir="rtl">
      <div className="filters">
        <div>
          <p className="eyebrow">اتصال رسمی Sanaei / 3x-ui</p>
          <h2>مرکز پنل‌های فروش</h2>
          <p>
            هر پلن می‌تواند از چند پنل و چند inbound انتخاب شود؛ نوشتن روی پنل تا عبور از
            تأیید عملیاتی بسته می‌ماند.
          </p>
        </div>
        <button className="btn secondary" type="button" onClick={reload} disabled={loading}>
          {loading ? "در حال دریافت…" : "تازه‌سازی"}
        </button>
      </div>
      {error ? (
        <p className="notice error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="cards">
        <article className="metric">
          <span>کل پنل‌ها</span>
          <strong>{panels.length.toLocaleString("fa-IR")}</strong>
          <small>بدون محدودیت نرم‌افزاری برای چندپنلی</small>
        </article>
        <article className="metric">
          <span>فعال و certified</span>
          <strong>{active.toLocaleString("fa-IR")}</strong>
          <small>نسخه واقعی با قرارداد v3.7.0 تطبیق یافته</small>
        </article>
        <article className="metric">
          <span>آمادهٔ sync</span>
          <strong>{inboundReady.toLocaleString("fa-IR")}</strong>
          <small>قابل استفاده در استخرهای تخصیص</small>
        </article>
        <article className="metric">
          <span>نیازمند اقدام</span>
          <strong>{needsAttention.toLocaleString("fa-IR")}</strong>
          <small>credential، نسخه یا اتصال باید بررسی شود</small>
        </article>
      </div>
    </section>
  );
}

export function ProviderInstanceTable(): React.ReactElement {
  const { panels, loading, error, reload } = usePanels();
  const [query, setQuery] = React.useState("");
  const visible = panels.filter((panel) =>
    `${panel.display_name} ${panel.public_reference} ${panel.provider_kind}`
      .toLocaleLowerCase("fa")
      .includes(query.trim().toLocaleLowerCase("fa")),
  );
  return (
    <section className="panel">
      <div className="filters">
        <a className="btn" href="/management/providers/new">
          افزودن پنل 3x-ui
        </a>
        <input
          aria-label="جستجوی پنل"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="نام یا مرجع پنل"
        />
        <button className="btn secondary" type="button" onClick={reload} disabled={loading}>
          تازه‌سازی
        </button>
      </div>
      {error ? (
        <p className="notice error" role="alert">
          {error}
        </p>
      ) : null}
      {!loading && visible.length === 0 ? (
        <EmptyState
          title="پنلی پیدا نشد"
          body="یک پنل رسمی 3x-ui v3.7.0 اضافه کنید یا فیلتر را پاک کنید."
        />
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>نام</th>
                <th>نوع و نسخه</th>
                <th>Credential</th>
                <th>آخرین تست</th>
                <th>وضعیت</th>
                <th>اقدام</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((panel) => (
                <tr key={panel.public_reference}>
                  <td>
                    <strong>{panel.display_name}</strong>
                    <br />
                    <Tech>{panel.public_reference}</Tech>
                  </td>
                  <td>
                    <Tech>{panel.provider_kind}</Tech>
                    <br />
                    <Tech>{panel.provider_version}</Tech>
                  </td>
                  <td>
                    <StatusBadge value={panel.credential.configured ? "ثبت شده" : "ثبت نشده"} />
                  </td>
                  <td>
                    {panel.last_connection_test ? (
                      <>
                        <StatusBadge
                          value={
                            statusFa[panel.last_connection_test.status] ??
                            panel.last_connection_test.status
                          }
                        />
                        <br />
                        <small>
                          {new Date(panel.last_connection_test.tested_at).toLocaleString("fa-IR")}
                        </small>
                      </>
                    ) : (
                      "تست نشده"
                    )}
                  </td>
                  <td>
                    <StatusBadge value={statusFa[panel.status] ?? panel.status} />
                  </td>
                  <td>
                    <a
                      className="pill"
                      href={`/management/providers/${encodeURIComponent(panel.public_reference)}`}
                    >
                      مدیریت
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

type ProviderFormProps = { panelReference?: string };

export function ProviderCredentialNotice({
  panelReference,
}: ProviderFormProps): React.ReactElement {
  const creating = !panelReference;
  const [displayName, setDisplayName] = React.useState("");
  const [origin, setOrigin] = React.useState("");
  const [basePath, setBasePath] = React.useState("");
  const [allowPrivate, setAllowPrivate] = React.useState(false);
  const [authMode, setAuthMode] = React.useState<"bearer_token" | "username_password">(
    "bearer_token",
  );
  const [bearer, setBearer] = React.useState("");
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");

  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      let reference = panelReference;
      if (!reference) {
        const panel = await providerApi.create({
          display_name: displayName,
          provider_kind: "sanaei_3x_ui",
          provider_version: "v3.7.0",
          endpoint_origin: origin,
          base_path: basePath,
          endpoint_policy: {
            allow_private_network: allowPrivate,
            allowed_ports: [443, 8443],
            require_https: true,
            max_response_bytes: 2_000_000,
          },
        });
        reference = panel.public_reference;
      }
      const hasSecret =
        authMode === "bearer_token" ? Boolean(bearer) : Boolean(username && password);
      if (hasSecret) {
        await providerApi.replaceCredential(
          reference,
          authMode === "bearer_token"
            ? { auth_mode: authMode, bearer_token: bearer }
            : { auth_mode: authMode, username, password },
        );
      }
      setBearer("");
      setPassword("");
      setMessage(creating ? "پنل با موفقیت ثبت شد." : "credential با موفقیت جایگزین شد.");
      if (creating) {
        window.location.assign(`/management/providers/${encodeURIComponent(reference)}`);
      }
    } catch (reason: unknown) {
      setError(messageOf(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel stack" onSubmit={(event) => void submit(event)}>
      <h2>{creating ? "افزودن پنل رسمی 3x-ui" : "جایگزینی امن credential"}</h2>
      <p className="notice">
        مقدار محرمانه فقط یک‌بار با TLS ارسال، روی سرور رمزگذاری و بلافاصله از فرم پاک
        می‌شود؛ API هرگز آن را برنمی‌گرداند.
      </p>
      {creating ? (
        <>
          <label className="field">
            نام نمایشی
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
              minLength={2}
            />
          </label>
          <label className="field">
            آدرس اصلی پنل
            <input
              dir="ltr"
              type="url"
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
              placeholder="https://panel.example.com"
              required
            />
          </label>
          <label className="field">
            Base path اختیاری
            <input
              dir="ltr"
              value={basePath}
              onChange={(event) => setBasePath(event.target.value)}
              placeholder="/secret-path"
            />
          </label>
          <label className="field">
            <input
              type="checkbox"
              checked={allowPrivate}
              onChange={(event) => setAllowPrivate(event.target.checked)}
            />{" "}
            پنل داخل شبکه خصوصی/VPN است
          </label>
        </>
      ) : null}
      <label className="field">
        روش احراز هویت
        <select
          value={authMode}
          onChange={(event) => setAuthMode(event.target.value as typeof authMode)}
        >
          <option value="bearer_token">API Token با scope ادمین (پیشنهادی)</option>
          <option value="username_password">نام کاربری و گذرواژه</option>
        </select>
      </label>
      {authMode === "bearer_token" ? (
        <label className="field">
          API Token
          <input
            type="password"
            autoComplete="new-password"
            value={bearer}
            onChange={(event) => setBearer(event.target.value)}
            required={!creating}
          />
        </label>
      ) : (
        <>
          <label className="field">
            نام کاربری
            <input
              dir="ltr"
              autoComplete="off"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required={!creating}
            />
          </label>
          <label className="field">
            گذرواژه
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required={!creating}
            />
          </label>
        </>
      )}
      {error ? (
        <p className="notice error" role="alert">
          {error}
        </p>
      ) : null}
      {message ? (
        <p className="notice" role="status">
          {message}
        </p>
      ) : null}
      <button className="btn" disabled={busy || (creating && (!displayName || !origin))}>
        {busy ? "در حال ثبت امن…" : creating ? "ثبت پنل" : "جایگزینی credential"}
      </button>
    </form>
  );
}

export function ProviderPanelDetail({
  panelReference,
}: Required<ProviderFormProps>): React.ReactElement {
  const [panel, setPanel] = React.useState<ProviderPanel | null>(null);
  const [busy, setBusy] = React.useState("");
  const [result, setResult] = React.useState("");
  const [error, setError] = React.useState("");
  const load = React.useCallback(
    () => providerApi.panel(panelReference).then(setPanel),
    [panelReference],
  );
  React.useEffect(() => {
    void load().catch((reason: unknown) => setError(messageOf(reason)));
  }, [load]);
  async function run(kind: "test" | "sync"): Promise<void> {
    setBusy(kind);
    setError("");
    setResult("");
    try {
      if (kind === "test") {
        const value = await providerApi.test(panelReference);
        setResult(
          `نتیجه تست: ${statusFa[value.status] ?? value.status}${value.safe_error_code ? ` — ${value.safe_error_code}` : ""}`,
        );
      } else {
        const value = await providerApi.sync(panelReference);
        setResult(
          `همگام‌سازی ${statusFa[value.status] ?? value.status}؛ ${value.inbound_count.toLocaleString("fa-IR")} inbound دریافت شد.`,
        );
      }
      await load();
    } catch (reason: unknown) {
      setError(messageOf(reason));
    } finally {
      setBusy("");
    }
  }
  if (!panel)
    return (
      <section className="panel">
        <p>{error || "در حال دریافت پنل…"}</p>
      </section>
    );
  return (
    <section className="panel stack">
      <div className="filters">
        <div>
          <p className="eyebrow">{panel.public_reference}</p>
          <h2>{panel.display_name}</h2>
        </div>
        <StatusBadge value={statusFa[panel.status] ?? panel.status} />
      </div>
      <div className="cards">
        <article className="metric">
          <span>نسخه قرارداد</span>
          <strong>{panel.provider_version}</strong>
          <small>کاملاً جدا از نسخه قدیمی v3.5.0</small>
        </article>
        <article className="metric">
          <span>Credential</span>
          <strong>{panel.credential.configured ? "ثبت شده" : "ثبت نشده"}</strong>
          <small>{panel.credential.credential_kind ?? "—"}</small>
        </article>
        <article className="metric">
          <span>آخرین تست</span>
          <strong>{statusFa[panel.last_connection_test?.status ?? ""] ?? "تست نشده"}</strong>
          <small>{panel.last_connection_test?.detected_version ?? "—"}</small>
        </article>
      </div>
      <dl>
        <dt>Endpoint</dt>
        <dd>
          <Tech>
            {panel.endpoint_origin}
            {panel.base_path}
          </Tech>
        </dd>
        <dt>نسخه خوش‌بینانه</dt>
        <dd>{panel.optimistic_version.toLocaleString("fa-IR")}</dd>
      </dl>
      <div className="actions">
        <button
          className="btn"
          type="button"
          disabled={Boolean(busy)}
          onClick={() => void run("test")}
        >
          {busy === "test" ? "در حال تست…" : "تست اتصال و نسخه"}
        </button>
        <button
          className="btn secondary"
          type="button"
          disabled={Boolean(busy)}
          onClick={() => void run("sync")}
        >
          {busy === "sync" ? "در حال همگام‌سازی…" : "دریافت inboundها"}
        </button>
        <a
          className="pill"
          href={`/management/providers/${encodeURIComponent(panelReference)}/inventory`}
        >
          مشاهده inboundها
        </a>
        <a
          className="pill"
          href={`/management/providers/${encodeURIComponent(panelReference)}/capabilities`}
        >
          قابلیت‌ها
        </a>
      </div>
      {result ? (
        <p className="notice" role="status">
          {result}
        </p>
      ) : null}
      {error ? (
        <p className="notice error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

export function ProviderCapabilityMatrix({
  panelReference,
}: Required<ProviderFormProps>): React.ReactElement {
  const [data, setData] = React.useState<ProviderCapability | null>(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    void providerApi
      .capabilities(panelReference)
      .then(setData)
      .catch((reason: unknown) => setError(messageOf(reason)));
  }, [panelReference]);
  if (!data)
    return (
      <section className="panel">
        <p>{error || "در حال دریافت قابلیت‌ها…"}</p>
      </section>
    );
  return (
    <section className="panel stack">
      <h2>قرارداد certified</h2>
      <p>
        <Tech>
          {data.provider_kind} {data.provider_version}
        </Tech>
      </p>
      <p>
        Scope لازم: <Tech>{data.required_bearer_scope}</Tech>
      </p>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>عملیات</th>
              <th>وضعیت قرارداد</th>
            </tr>
          </thead>
          <tbody>
            {data.operations.map((operation) => (
              <tr key={operation}>
                <td>
                  <Tech>{operation}</Tech>
                </td>
                <td>
                  <StatusBadge
                    value={
                      operation.includes("add") ||
                      operation.includes("attach") ||
                      operation.includes("detach")
                        ? "گیت نوشتن لازم است"
                        : "read-only مجاز"
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="notice">
        فعال بودن عملیات در قرارداد به معنی فعال بودن production write نیست؛ پیش‌فرض:{" "}
        {String(data.writes_enabled_by_default)}
      </p>
    </section>
  );
}

export function ProviderInventoryView({
  panelReference,
}: Required<ProviderFormProps>): React.ReactElement {
  const [items, setItems] = React.useState<ProviderInbound[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const load = React.useCallback(() => {
    setLoading(true);
    return providerApi
      .inbounds(panelReference)
      .then(setItems)
      .catch((reason: unknown) => setError(messageOf(reason)))
      .finally(() => setLoading(false));
  }, [panelReference]);
  React.useEffect(() => {
    void load();
  }, [load]);
  return (
    <section className="panel">
      <div className="filters">
        <div>
          <h2>Inboundهای همگام‌شده</h2>
          <p>این جدول فقط projection امن آخرین syncهاست.</p>
        </div>
        <button
          className="btn secondary"
          type="button"
          onClick={() => void load()}
          disabled={loading}
        >
          تازه‌سازی
        </button>
      </div>
      {error ? <p className="notice error">{error}</p> : null}
      {!loading && items.length === 0 ? (
        <EmptyState
          title="هنوز inboundی دریافت نشده"
          body="در صفحه پنل، تست اتصال و سپس دریافت inboundها را اجرا کنید."
        />
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID در پنل</th>
                <th>نام</th>
                <th>پروتکل</th>
                <th>پورت</th>
                <th>وضعیت</th>
                <th>مشاهده</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={`${item.sync_reference}-${item.remote_identifier}`}>
                  <td>
                    <Tech>{item.remote_identifier}</Tech>
                  </td>
                  <td>{item.sanitized_payload.remark ?? item.sanitized_payload.tag ?? "—"}</td>
                  <td>
                    <Tech>{item.sanitized_payload.protocol}</Tech>
                  </td>
                  <td>{item.sanitized_payload.port?.toLocaleString("fa-IR") ?? "—"}</td>
                  <td>
                    <StatusBadge value={item.status} />
                  </td>
                  <td>
                    <small>{new Date(item.observed_at).toLocaleString("fa-IR")}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
