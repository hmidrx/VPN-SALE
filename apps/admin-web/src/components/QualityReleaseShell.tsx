import React from "react";
import { ManagementShell, StatusBadge, Tech } from "./ManagementShell";

const gates = [
  ["REQUIRED_CI", "PASSED", "CI_SAFE"],
  ["AUTHORIZATION_MATRIX", "PASSED", "CI_SAFE"],
  ["LOAD_BASELINE", "PASSED_WITH_LIMITATIONS", "LOCAL_ISOLATED"],
  ["STRESS_RECOVERY", "NOT_RUN", "STAGING_LOAD"],
  ["CHAOS_RECOVERY", "NOT_RUN", "STAGING_CHAOS"],
  ["BACKUP_RESTORE", "PASSED_WITH_LIMITATIONS", "LOCAL_ISOLATED"],
  ["PROVIDER_CERTIFICATION", "NOT_RUN", "STAGING_STANDARD"],
  ["CRITICAL_HIGH_DEFECTS", "PASSED", "CI_SAFE"],
] as const;

const profiles = ["CI_SAFE", "LOCAL_ISOLATED", "STAGING_STANDARD", "STAGING_LOAD", "STAGING_SECURITY", "STAGING_CHAOS"] as const;

export function QualityOverview(): React.ReactElement {
  return (
    <ManagementShell title="کنسول کیفیت و انتشار" eyebrow="Milestone 7-A2" required="quality.read">
      <section className="grid cards">
        <article><h2>پروفایل‌های اجرایی</h2><p>اجرای عادی فقط CI_SAFE و LOCAL_ISOLATED است؛ بار، امنیت و آشوب staging نیازمند allowlist و تأیید تایپی هستند.</p>{profiles.map((profile) => <Tech key={profile}>{profile}</Tech>)}</article>
        <article><h2>تصمیم نهایی</h2><StatusBadge value="READY_FOR_RC_REVIEW یا NO_GO" /><p>هیچ مسیر خودکار GO_TO_PRODUCTION یا دکمه deploy تولید وجود ندارد.</p></article>
        <article><h2>حفاظت داده</h2><p>گزارش‌ها فقط digest، timestamp و خلاصه sanitize شده دارند؛ payload خام scanner، secret، token اشتراک و داده مشتری نمایش داده نمی‌شود.</p></article>
      </section>
      <GateTable />
    </ManagementShell>
  );
}

export function GateTable(): React.ReactElement {
  return <section><h2>دروازه‌های انتشار</h2><div className="table" role="table" aria-label="release gates">{gates.map(([name, state, profile]) => <div className="row" role="row" key={name}><Tech>{name}</Tech><StatusBadge value={state} /><Tech>{profile}</Tech></div>)}</div></section>;
}

export function PerformanceQualityPage(): React.ReactElement {
  return <ManagementShell title="کارایی و بار" eyebrow="Milestone 7-A2" required="quality.performance.read"><section className="panel"><h2>بودجه‌ها</h2><p>p95، p99، نرخ خطا، timeout، عمق صف، outbox lag، CPU، memory، DB wait و Redis latency با فرض staging نسخه‌گذاری می‌شوند.</p><Tech>mixed-critical-journeys-ci-safe</Tech><Tech>baseline/spike/stress/soak</Tech></section></ManagementShell>;
}

export function SecurityQualityPage(): React.ReactElement {
  return <ManagementShell title="امنیت و DAST ایزوله" eyebrow="Milestone 7-A2" required="quality.security.read"><section className="panel"><h2>روش ارزیابی</h2><p>DAST فقط روی origin staging allowlist شده، با payload امن، نرخ محدود و review دستی false-positive اجرا می‌شود.</p><StatusBadge value="NOT_RUN for unavailable staging" /></section></ManagementShell>;
}

export function ChaosQualityPage(): React.ReactElement {
  return <ManagementShell title="آشوب و بازیابی" eyebrow="Milestone 7-A2" required="quality.chaos.read"><section className="panel"><h2>مرز fault injection</h2><p>سناریوها زمان‌دار، غیرتولیدی و دارای cleanup هستند؛ PostgreSQL/Redis/provider timeout/restart بدون duplicate side effect بررسی می‌شود.</p><StatusBadge value="STAGING_CHAOS requires confirmation" /></section></ManagementShell>;
}

export function DefectsPage(): React.ReactElement {
  return <ManagementShell title="دفتر نقص‌های انتشار" eyebrow="Milestone 7-A2" required="quality.defects.read"><section className="panel"><h2>سیاست نقص</h2><p>Critical و High تا زمان regression و verification مسدودکننده‌اند؛ Fixed به معنی Verified نیست.</p><StatusBadge value="0 Critical/High known in synthetic evidence" /></section></ManagementShell>;
}

export function ReleaseCandidatesPage(): React.ReactElement {
  return <ManagementShell title="Release Candidates" eyebrow="Milestone 7-A2" required="releases.candidates.read"><section className="panel"><h2>Provenance</h2><p>RC شناسه، commit، migration head، digest artifact، SBOM و evidence را bind می‌کند و پس از finalization immutable است.</p><Tech>no latest tag</Tech></section><GateTable /></ManagementShell>;
}

export function GoNoGoPage(): React.ReactElement {
  return <ManagementShell title="Go / No-Go" eyebrow="Milestone 7-A2" required="releases.go_no_go.read"><section className="panel"><h2>توصیه sanitize شده</h2><StatusBadge value="READY_FOR_RC_REVIEW" /><p>تصمیم تولید دستی است و live-provider های بدون credential به صورت NOT_RUN باقی می‌مانند.</p></section></ManagementShell>;
}
