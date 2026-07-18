import React from "react";
import { Tech, StatusBadge, EmptyState } from "../components/ManagementShell";

export const providerPermissions = {
  read: "providers.read",
  manage: "providers.manage",
  credentials: "providers.manage_credentials",
  test: "providers.test_connection",
  sync: "providers.sync",
  inventory: "providers.read_inventory",
  diagnostics: "providers.read_diagnostics",
  certify: "providers.certify",
  writeContracts: "providers.write_contracts.read",
  writePreflight: "providers.write_preflight",
  writePlans: "providers.write_plans.read",
  writeCertificationPrepare: "providers.write_certification.prepare",
  writeCertificationReview: "providers.write_certification.review",
} as const;

export function ProviderDashboard(): React.ReactElement {
  return <section className="panel stack" dir="rtl"><h2>هسته ارائه‌دهندگان VPN</h2><p>این کنسول برای اتصال امن، تشخیص نسخه، قابلیت‌ها، همگام‌سازی read-only و آمادگی نوشتن بدون اجرای mutation است.</p><div className="cards"><article className="metric"><span>نسخه‌های certified</span><strong>3</strong><small className="tech">3x-ui v3.5.0 / x-ui v1.11.3 / PasarGuard v4.0.2</small></article><article className="metric"><span>وضعیت live</span><strong>LIVE_UNVERIFIED</strong><small>تا اجرای certification روی staging واقعی.</small></article><article className="metric"><span>عملیات نوشتن</span><strong>غیرفعال</strong><small className="tech">PROVIDER_WRITE_NOT_ENABLED</small></article></div></section>;
}

export function ProviderInstanceTable(): React.ReactElement {
  return <section className="panel"><div className="filters"><a className="btn" href="/management/providers/new">افزودن پنل</a><input className="ltr" placeholder="panel_reference" /></div><div className="table-wrap"><table className="data-table"><thead><tr><th>نام</th><th>نوع</th><th>نسخه</th><th>قرارداد</th><th>وضعیت</th><th>اقدام</th></tr></thead><tbody><tr><td>از API واقعی</td><td><Tech>sanaei_3x_ui</Tech></td><td><Tech>v3.5.0</Tech></td><td><StatusBadge value="CONTRACT_VERIFIED" /></td><td><StatusBadge value="LIVE_UNVERIFIED" /></td><td><a className="pill" href="/management/providers/example-panel">جزئیات</a></td></tr></tbody></table></div></section>;
}

export function ProviderCredentialNotice(): React.ReactElement {
  return <section className="notice error"><h2>ورود یک‌طرفه credential</h2><p>رمز، API token، API key، cookie و CSRF هرگز در DOM، localStorage یا پاسخ read بازگردانده نمی‌شوند.</p><label className="field">مقدار محرمانه<input type="password" autoComplete="new-password" /></label><button className="btn" type="button">ارسال به vault</button></section>;
}

export function ProviderCapabilityMatrix(): React.ReactElement {
  const rows = ["PANEL_VERSION_READ", "NODE_LIST", "INBOUND_LIST", "CLIENT_LIST", "HOST_LIST", "CLIENT_CREATE", "CLIENT_UPDATE", "CLIENT_TRAFFIC_RESET"];
  return <section className="panel"><h2>ماتریس قابلیت</h2><div className="table-wrap"><table className="data-table"><tbody>{rows.map((r) => <tr key={r}><td><Tech>{r}</Tech></td><td><StatusBadge value={r === "CLIENT_CREATE" ? "disabled_by_policy" : "supported/unsupported by certified contract"} /></td><td>evidence: docs/provider-contracts</td></tr>)}</tbody></table></div></section>;
}

export function ProviderInventoryView(): React.ReactElement {
  return <section className="panel"><h2>Inventory normalized</h2><p>شناسه‌های remote دقیقاً حفظ می‌شوند اما به UUID داخلی تبدیل نمی‌شوند.</p><EmptyState title="بدون موجودی ساختگی" body="nodes، inbounds، clients/users و hosts فقط پس از sync read-only واقعی یا mock قراردادی نمایش داده می‌شوند." /></section>;
}

export function ProviderWriteReadiness(): React.ReactElement {
  return <section className="panel stack" dir="rtl"><h2>آمادگی نوشتن ارائه‌دهنده</h2><p>هیچ دکمه‌ای mutation واقعی اجرا نمی‌کند؛ فقط preflight، dry-run plan، ابطال plan منقضی و گزارش sanitize شده مجاز است.</p><div className="cards"><article className="metric"><span>PasarGuard correction</span><strong className="tech">v4.0.2 / 0b0ddaa</strong><small>همه فرض‌های v5.1.0، OpenAPI و API-key پنل نامعتبر و نیازمند re-certification هستند.</small></article><article className="metric"><span>write state</span><strong className="tech">LIVE_WRITE_CANARY_REQUIRED</strong><small>production execution returns PROVIDER_WRITE_NOT_ENABLED.</small></article><article className="metric"><span>dry-run safety</span><strong>بدون secret</strong><small className="tech">no raw payload / no cookie / no UUID / no password / no full URL</small></article></div></section>;
}
