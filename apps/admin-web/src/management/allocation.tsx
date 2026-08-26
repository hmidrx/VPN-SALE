"use client";

import React from "react";

import { catalogApi, type CatalogApiError } from "../catalog/api";
import type { Product, ProductVersion } from "../catalog/types";
import { EmptyState, ManagementShell, StatusBadge, Tech } from "../components/ManagementShell";
import {
  AllocationApiError,
  allocationApi,
  type AllocationPolicy,
  type AllocationPolicyVersion,
  type AllocationPool,
  type AllocationSimulation,
  type AllocationTarget,
} from "./allocation-api";
import { providerApi, type ProviderInbound, type ProviderPanel } from "./providers-api";

const faError: Record<string, string> = {
  ALLOCATION_PANEL_CERTIFICATION_REQUIRED: "پنل باید تست اتصال موفق و قرارداد 3.7.0 معتبر داشته باشد.",
  ALLOCATION_INBOUND_NOT_SYNCED: "این inbound در آخرین همگام‌سازی پنل پیدا نشد.",
  ALLOCATION_INBOUND_PROTOCOL_MISMATCH: "پروتکل inbound با هدف انتخابی یکسان نیست.",
  ALLOCATION_NO_ELIGIBLE_TARGET: "هدف سالم و دارای ظرفیت کافی برای این سیاست وجود ندارد.",
  ALLOCATION_INVENTORY_STALE: "موجودی inbound قدیمی است؛ پنل را دوباره Sync کنید.",
  ALLOCATION_POLICY_TRANSITION_INVALID: "این نسخه در وضعیت مناسب این عملیات نیست.",
  CONCURRENT_MODIFICATION: "رکورد هم‌زمان تغییر کرده است؛ صفحه را تازه کنید.",
};

function messageOf(error: unknown): string {
  if (error instanceof AllocationApiError) {
    return faError[error.code] ?? `عملیات تخصیص انجام نشد (${error.code}).`;
  }
  if (error && typeof error === "object" && "detail" in error) {
    const catalog = error as CatalogApiError;
    return `خواندن کاتالوگ انجام نشد (${catalog.detail.code}).`;
  }
  return "ارتباط با API مدیریت برقرار نشد.";
}

function splitValues(value: string): string[] {
  return [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))];
}

function panelLabel(panels: ProviderPanel[], id: string): string {
  const panel = panels.find((item) => item.id === id);
  return panel ? `${panel.display_name} (${panel.public_reference})` : id;
}

export function AllocationPoolConsole(): React.ReactElement {
  const [pools, setPools] = React.useState<AllocationPool[]>([]);
  const [targets, setTargets] = React.useState<AllocationTarget[]>([]);
  const [panels, setPanels] = React.useState<ProviderPanel[]>([]);
  const [inbounds, setInbounds] = React.useState<ProviderInbound[]>([]);
  const [panelId, setPanelId] = React.useState("");
  const [poolId, setPoolId] = React.useState("");
  const [inboundId, setInboundId] = React.useState("");
  const [poolName, setPoolName] = React.useState("");
  const [capacity, setCapacity] = React.useState("1000");
  const [reserve, setReserve] = React.useState("20");
  const [priority, setPriority] = React.useState("100");
  const [tags, setTags] = React.useState("");
  const [writeEnabled, setWriteEnabled] = React.useState(false);
  const [sharedIdentity, setSharedIdentity] = React.useState(true);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  const load = React.useCallback(async (): Promise<void> => {
    const [poolRows, targetRows, panelRows] = await Promise.all([
      allocationApi.pools(),
      allocationApi.targets(),
      providerApi.panels(),
    ]);
    setPools(poolRows);
    setTargets(targetRows);
    setPanels(panelRows.items);
    setPoolId((current) => current || poolRows[0]?.id || "");
    setPanelId((current) => current || panelRows.items.find((p) => p.status === "ACTIVE")?.id || "");
  }, []);

  React.useEffect(() => {
    void load().catch((reason: unknown) => setError(messageOf(reason)));
  }, [load]);

  React.useEffect(() => {
    const panel = panels.find((item) => item.id === panelId);
    if (!panel) {
      setInbounds([]);
      return;
    }
    void providerApi
      .inbounds(panel.public_reference)
      .then((rows) => {
        setInbounds(rows.filter((row) => row.sanitized_payload.enabled !== false));
        setInboundId((current) =>
          rows.some((row) => row.remote_identifier === current)
            ? current
            : rows[0]?.remote_identifier || "",
        );
      })
      .catch((reason: unknown) => setError(messageOf(reason)));
  }, [panelId, panels]);

  async function run(label: string, action: () => Promise<void>): Promise<void> {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (reason: unknown) {
      setError(messageOf(reason));
    } finally {
      setBusy("");
    }
  }

  async function createPool(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    await run("pool", async () => {
      const row = await allocationApi.createPool({ name: poolName, status: "ACTIVE" });
      setPoolName("");
      setPoolId(row.id);
      setNotice("استخر فعال ایجاد شد.");
      await load();
    });
  }

  async function createTarget(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    const inbound = inbounds.find((item) => item.remote_identifier === inboundId);
    if (!inbound) {
      setError("یک inbound سینک‌شده انتخاب کنید.");
      return;
    }
    await run("target", async () => {
      await allocationApi.createTarget({
        pool_id: poolId,
        panel_id: panelId,
        inbound_id: inboundId,
        provider_kind: "sanaei_3x_ui",
        required_protocol: String(inbound.sanitized_payload.protocol || "vless").toLowerCase(),
        role: "REQUIRED",
        priority: Number(priority),
        weight: 100,
        max_capacity: Number(capacity),
        safety_reserve: Number(reserve),
        status: "ACTIVE",
        certification_minimum: "v3.7.0",
        diagnostics: {
          healthy: true,
          maintenance: false,
          write_mode: writeEnabled ? "WRITE_ENABLED" : "READ_ONLY",
          supports_shared_identity: sharedIdentity,
          tags: splitValues(tags),
        },
      });
      setNotice("هدف inbound با شواهد زنده پنل ثبت شد.");
      await load();
    });
  }

  async function toggleTarget(target: AllocationTarget): Promise<void> {
    await run(`target-${target.id}`, async () => {
      await allocationApi.updateTarget(target.id, {
        status: target.status === "ACTIVE" ? "DISABLED" : "ACTIVE",
      });
      await load();
    });
  }

  return (
    <ManagementShell title="استخرها، پنل‌ها و inboundها" required="allocation.manage">
      <section className="cards">
        <article className="panel metric"><span>استخر</span><strong>{pools.length.toLocaleString("fa-IR")}</strong><small>گروه‌بندی هدف‌های فروش</small></article>
        <article className="panel metric"><span>هدف inbound</span><strong>{targets.length.toLocaleString("fa-IR")}</strong><small>هر هدف به موجودی سینک‌شده متصل است</small></article>
        <article className="panel metric"><span>پنل فعال</span><strong>{panels.filter((item) => item.status === "ACTIVE").length.toLocaleString("fa-IR")}</strong><small>قرارداد رسمی v3.7.0</small></article>
      </section>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {notice ? <p className="notice" role="status">{notice}</p> : null}
      <section className="panel">
        <h2>ساخت استخر</h2>
        <form className="filters" onSubmit={(event) => void createPool(event)}>
          <label>نام استخر<input value={poolName} onChange={(event) => setPoolName(event.target.value)} minLength={1} maxLength={120} required /></label>
          <button className="btn" disabled={Boolean(busy)}>ایجاد استخر فعال</button>
        </form>
      </section>
      <section className="panel">
        <h2>افزودن inbound سینک‌شده به استخر</h2>
        <p className="notice">فعال‌کردن Write فقط هدف را برای سیاست واجد شرایط می‌کند؛ Worker نیز باید جداگانه مجوز تولید و certification معتبر داشته باشد.</p>
        <form className="confirm" onSubmit={(event) => void createTarget(event)}>
          <label>استخر<select value={poolId} onChange={(event) => setPoolId(event.target.value)} required>{pools.map((pool) => <option value={pool.id} key={pool.id}>{pool.name} — {pool.status}</option>)}</select></label>
          <label>پنل<select value={panelId} onChange={(event) => setPanelId(event.target.value)} required><option value="">انتخاب پنل</option>{panels.map((panel) => <option value={panel.id} key={panel.id} disabled={panel.status !== "ACTIVE"}>{panel.display_name} — {panel.status}</option>)}</select></label>
          <label>Inbound<select value={inboundId} onChange={(event) => setInboundId(event.target.value)} required><option value="">انتخاب inbound</option>{inbounds.map((inbound) => <option value={inbound.remote_identifier} key={inbound.remote_identifier}>#{inbound.remote_identifier} — {String(inbound.sanitized_payload.remark || inbound.sanitized_payload.tag || "بدون نام")} — {String(inbound.sanitized_payload.protocol || "نامشخص")}</option>)}</select></label>
          <label>ظرفیت هویت فعال<input type="number" min="1" value={capacity} onChange={(event) => setCapacity(event.target.value)} required /></label>
          <label>رزرو ایمنی<input type="number" min="0" value={reserve} onChange={(event) => setReserve(event.target.value)} required /></label>
          <label>اولویت؛ عدد کمتر زودتر<input type="number" min="0" value={priority} onChange={(event) => setPriority(event.target.value)} required /></label>
          <label>تگ‌ها با ویرگول<input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="premium, iran" /></label>
          <label className="pill"><input type="checkbox" checked={sharedIdentity} onChange={(event) => setSharedIdentity(event.target.checked)} /> هویت مشترک روی چند inbound</label>
          <label className="pill"><input type="checkbox" checked={writeEnabled} onChange={(event) => setWriteEnabled(event.target.checked)} /> واجد شرایط نوشتن کنترل‌شده</label>
          <button className="btn danger" disabled={Boolean(busy) || !poolId || !panelId || !inboundId}>{busy === "target" ? "در حال اعتبارسنجی…" : "اعتبارسنجی زنده و ثبت هدف"}</button>
        </form>
      </section>
      <section className="panel">
        <h2>اهداف تخصیص</h2>
        {targets.length === 0 ? <EmptyState title="هدفی ثبت نشده" body="پس از Sync پنل، inbound را از فرم بالا به استخر اضافه کنید." /> : <div className="table-wrap"><table className="data-table"><thead><tr><th>استخر</th><th>پنل</th><th>Inbound</th><th>پروتکل</th><th>ظرفیت</th><th>Write</th><th>سلامت</th><th>اقدام</th></tr></thead><tbody>{targets.map((target) => <tr key={target.id}><td>{pools.find((pool) => pool.id === target.pool_id)?.name || target.pool_id}</td><td>{panelLabel(panels, target.panel_id)}</td><td><Tech>{target.inbound_id}</Tech></td><td><Tech>{target.required_protocol}</Tech></td><td>{target.max_capacity.toLocaleString("fa-IR")} − {target.safety_reserve.toLocaleString("fa-IR")}</td><td><StatusBadge value={target.diagnostics.write_mode} /></td><td><StatusBadge value={target.status === "ACTIVE" && target.diagnostics.healthy ? "سالم" : target.status} /></td><td><button className="btn secondary" type="button" disabled={Boolean(busy)} onClick={() => void toggleTarget(target)}>{target.status === "ACTIVE" ? "غیرفعال" : "فعال"}</button></td></tr>)}</tbody></table></div>}
      </section>
    </ManagementShell>
  );
}

type PublishedPlan = { product: Product; version: ProductVersion };

export function AllocationPolicyConsole(): React.ReactElement {
  const [pools, setPools] = React.useState<AllocationPool[]>([]);
  const [policies, setPolicies] = React.useState<AllocationPolicy[]>([]);
  const [versions, setVersions] = React.useState<AllocationPolicyVersion[]>([]);
  const [plans, setPlans] = React.useState<PublishedPlan[]>([]);
  const [policyId, setPolicyId] = React.useState("");
  const [policyName, setPolicyName] = React.useState("");
  const [selectedPools, setSelectedPools] = React.useState<string[]>([]);
  const [productVersionId, setProductVersionId] = React.useState("");
  const [planReference, setPlanReference] = React.useState("standard_plan");
  const [location, setLocation] = React.useState("");
  const [count, setCount] = React.useState("1");
  const [strategy, setStrategy] = React.useState("SINGLE_TARGET");
  const [identityStrategy, setIdentityStrategy] = React.useState("PER_ATTACHMENT");
  const [tags, setTags] = React.useState("");
  const [protocols, setProtocols] = React.useState("vless");
  const [simulation, setSimulation] = React.useState<AllocationSimulation | null>(null);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  const load = React.useCallback(async (): Promise<void> => {
    const [poolRows, policyRows, productsPage] = await Promise.all([
      allocationApi.pools(),
      allocationApi.policies(),
      catalogApi.products({ status_filter: "ACTIVE", limit: 100 }),
    ]);
    const versionPages = await Promise.all(
      productsPage.items.map(async (product) => ({
        product,
        page: await catalogApi.productVersions(product.id),
      })),
    );
    const published = versionPages.flatMap(({ product, page }) =>
      page.items
        .filter((version) => version.status === "PUBLISHED")
        .map((version) => ({ product, version })),
    );
    setPools(poolRows);
    setPolicies(policyRows);
    setPlans(published);
    setPolicyId((current) => current || policyRows[0]?.id || "");
    setSelectedPools((current) => current.length ? current : poolRows.slice(0, 1).map((row) => row.id));
    setProductVersionId((current) => current || published[0]?.version.id || "");
  }, []);

  React.useEffect(() => {
    void load().catch((reason: unknown) => setError(messageOf(reason)));
  }, [load]);

  React.useEffect(() => {
    if (!policyId) {
      setVersions([]);
      return;
    }
    void allocationApi.versions(policyId).then(setVersions).catch((reason: unknown) => setError(messageOf(reason)));
  }, [policyId]);

  async function run(label: string, action: () => Promise<void>): Promise<void> {
    setBusy(label);
    setError("");
    setNotice("");
    try { await action(); } catch (reason: unknown) { setError(messageOf(reason)); } finally { setBusy(""); }
  }

  async function refreshPolicy(policy: string): Promise<void> {
    const [policyRows, versionRows] = await Promise.all([allocationApi.policies(), allocationApi.versions(policy)]);
    setPolicies(policyRows);
    setVersions(versionRows);
  }

  async function createPolicy(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    await run("policy", async () => {
      const row = await allocationApi.createPolicy({ name: policyName });
      setPolicyName("");
      setPolicyId(row.id);
      setNotice("سیاست پیش‌نویس ایجاد شد.");
      await refreshPolicy(row.id);
    });
  }

  async function createVersion(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    await run("version", async () => {
      const required = Number(count);
      await allocationApi.createVersion(policyId, {
        strategy,
        success_policy: strategy === "AT_LEAST_N_TARGETS" ? "AT_LEAST_N" : strategy === "ALL_REQUIRED_TARGETS" ? "ALL_REQUIRED" : "AT_LEAST_ONE",
        identity_strategy: identityStrategy,
        required_target_count: required,
        pool_ids: selectedPools,
        required_tags: splitValues(tags),
        product_version_ids: [productVersionId],
        plan_references: [planReference],
        locations: splitValues(location),
        required_protocols: splitValues(protocols),
      });
      setNotice("نسخه غیرقابل‌تغییر سیاست ساخته شد؛ اکنون اعتبارسنجی کنید.");
      await refreshPolicy(policyId);
    });
  }

  async function transition(version: AllocationPolicyVersion, action: "validate" | "publish"): Promise<void> {
    await run(`${action}-${version.id}`, async () => {
      const result = action === "validate"
        ? await allocationApi.validateVersion(version.policy_id, version.id, version.policy_optimistic_version)
        : await allocationApi.publishVersion(version.policy_id, version.id, version.policy_optimistic_version);
      setNotice(action === "validate" ? "ظرفیت، certification و inboundها معتبرند." : "نسخه برای فروش منتشر شد.");
      await refreshPolicy(result.policy_id);
    });
  }

  async function simulate(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    await run("simulate", async () => {
      const result = await allocationApi.simulate({
        product_version_id: productVersionId,
        plan_reference: planReference,
        location: location.trim() || null,
        required_attachment_count: Number(count),
      });
      setSimulation(result);
      setNotice("شبیه‌سازی بدون رزرو ظرفیت و بدون تماس نوشتنی با پنل انجام شد.");
    });
  }

  return (
    <ManagementShell title="سیاست‌های چندپنلی و چنداینباندی" required="allocation.publish">
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {notice ? <p className="notice" role="status">{notice}</p> : null}
      <section className="panel"><h2>ساخت سیاست</h2><form className="filters" onSubmit={(event) => void createPolicy(event)}><label>نام سیاست<input value={policyName} onChange={(event) => setPolicyName(event.target.value)} minLength={1} maxLength={120} required /></label><button className="btn" disabled={Boolean(busy)}>ایجاد پیش‌نویس</button></form><label>سیاست فعال<select value={policyId} onChange={(event) => setPolicyId(event.target.value)}><option value="">انتخاب سیاست</option>{policies.map((policy) => <option key={policy.id} value={policy.id}>{policy.name} — {policy.status} — v{policy.optimistic_version}</option>)}</select></label></section>
      <section className="panel"><h2>نسخه سیاست برای یک پلن</h2>{plans.length === 0 ? <p className="notice error">ابتدا یک محصول و نسخه کاتالوگ را منتشر کنید.</p> : null}<form className="confirm" onSubmit={(event) => void createVersion(event)}><label>نسخه منتشرشده محصول<select value={productVersionId} onChange={(event) => setProductVersionId(event.target.value)} required>{plans.map(({ product, version }) => <option value={version.id} key={version.id}>{product.machine_code} — نسخه {version.version_number} — {version.id}</option>)}</select></label><label>شناسه پلن<input dir="ltr" pattern="[a-z][a-z0-9_]{1,78}" value={planReference} onChange={(event) => setPlanReference(event.target.value)} required /></label><label>لوکیشن‌ها با ویرگول<input dir="ltr" value={location} onChange={(event) => setLocation(event.target.value)} placeholder="ir,de" /></label><label>استراتژی<select value={strategy} onChange={(event) => { setStrategy(event.target.value); if (event.target.value === "SINGLE_TARGET") setCount("1"); }}><option value="SINGLE_TARGET">یک هدف</option><option value="ALL_REQUIRED_TARGETS">تمام هدف‌های لازم</option><option value="AT_LEAST_N_TARGETS">حداقل N هدف</option></select></label><label>تعداد attachment لازم<input type="number" min="1" max="8" value={count} onChange={(event) => setCount(event.target.value)} disabled={strategy === "SINGLE_TARGET"} /></label><label>هویت<select value={identityStrategy} onChange={(event) => setIdentityStrategy(event.target.value)}><option value="PER_ATTACHMENT">مجزا برای هر inbound</option><option value="SHARED">یک هویت مشترک</option></select></label><label>پروتکل‌های مجاز<input dir="ltr" value={protocols} onChange={(event) => setProtocols(event.target.value)} required /></label><label>تگ‌های لازم<input dir="ltr" value={tags} onChange={(event) => setTags(event.target.value)} placeholder="premium" /></label><fieldset><legend>استخرهای قابل انتخاب</legend>{pools.map((pool) => <label className="pill" key={pool.id}><input type="checkbox" checked={selectedPools.includes(pool.id)} onChange={(event) => setSelectedPools((current) => event.target.checked ? [...current, pool.id] : current.filter((id) => id !== pool.id))} /> {pool.name} ({pool.target_count.toLocaleString("fa-IR")})</label>)}</fieldset><button className="btn" disabled={Boolean(busy) || !policyId || !productVersionId || selectedPools.length === 0}>ساخت نسخه immutable</button><button className="btn secondary" type="button" disabled={Boolean(busy) || !productVersionId} onClick={(event) => void simulate(event as unknown as React.FormEvent)}>شبیه‌سازی همین انتخاب</button></form></section>
      <section className="panel"><h2>نسخه‌ها و انتشار</h2>{versions.length === 0 ? <EmptyState title="نسخه‌ای وجود ندارد" body="یک نسخه سیاست برای محصول منتشرشده بسازید." /> : <div className="table-wrap"><table className="data-table"><thead><tr><th>نسخه</th><th>استراتژی</th><th>تعداد</th><th>پلن</th><th>استخر</th><th>وضعیت</th><th>گردش‌کار</th></tr></thead><tbody>{versions.map((version) => <tr key={version.id}><td><Tech>{version.version_number}</Tech></td><td><Tech>{version.strategy}</Tech></td><td>{version.required_target_count.toLocaleString("fa-IR")}</td><td><Tech>{version.plan_references.join(", ")}</Tech></td><td>{version.pool_ids.length.toLocaleString("fa-IR")}</td><td><StatusBadge value={version.status} /></td><td><div className="actions">{version.status === "DRAFT" ? <button className="btn secondary" type="button" disabled={Boolean(busy)} onClick={() => void transition(version, "validate")}>اعتبارسنجی</button> : null}{version.status === "VALIDATED" ? <button className="btn danger" type="button" disabled={Boolean(busy)} onClick={() => void transition(version, "publish")}>انتشار برای فروش</button> : null}</div></td></tr>)}</tbody></table></div>}</section>
      {simulation ? <section className="panel"><h2>نتیجه شبیه‌سازی امن</h2><p><StatusBadge value={simulation.selected_targets.length ? "ELIGIBLE" : "BLOCKED"} /> سیاست <Tech>{simulation.policy_version_id}</Tech></p><div className="table-wrap"><table className="data-table"><thead><tr><th>Target</th><th>Panel</th><th>Inbound</th><th>Provider</th></tr></thead><tbody>{simulation.selected_targets.map((target) => <tr key={target.target_id}><td><Tech>{target.target_id}</Tech></td><td><Tech>{target.panel_id}</Tech></td><td><Tech>{target.inbound_id}</Tech></td><td><Tech>{target.provider_kind}</Tech></td></tr>)}</tbody></table></div>{simulation.rejected_reason_codes.length ? <p className="notice error">دلایل رد: {simulation.rejected_reason_codes.join("، ")}</p> : null}<p className="notice">رزرو: {String(simulation.performs_reservation)}؛ تغییر پنل: {String(simulation.performs_provider_mutation)}</p></section> : null}
    </ManagementShell>
  );
}
