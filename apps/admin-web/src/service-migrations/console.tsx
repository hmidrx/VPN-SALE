import type { FailoverProposalSummary, MigrationPhase, MigrationSummary, OrphanIdentitySummary } from "./types";

const phaseLabels: Record<MigrationPhase, string> = {
  source: "مبدأ",
  target: "مقصد",
  cutover: "برش تحویل",
  cleanup: "پاک‌سازی",
  rollback: "بازگشت",
};

export function MigrationPhaseRail({ active }: { active: MigrationPhase }) {
  return (
    <ol className="phaseRail" aria-label="مراحل مهاجرت سرویس">
      {(Object.keys(phaseLabels) as MigrationPhase[]).map((phase) => (
        <li key={phase} data-active={phase === active}>
          <span>{phaseLabels[phase]}</span>
        </li>
      ))}
    </ol>
  );
}

export function MigrationDashboard({ migrations }: { migrations: MigrationSummary[] }) {
  return (
    <section dir="rtl" className="managementPanel">
      <header>
        <p className="eyebrow">Milestone 6-C2</p>
        <h1>کنسول مهاجرت سرویس</h1>
        <p>مهاجرت کنترل‌شده بدون نمایش شناسه پنل، نود، اینباند، توکن یا credential.</p>
      </header>
      <MigrationPhaseRail active="target" />
      <div className="cardGrid">
        {migrations.map((migration) => (
          <article key={migration.migrationReference} className="opsCard">
            <h2 className="ltr">{migration.migrationReference}</h2>
            <p>وضعیت: <strong>{migration.status}</strong></p>
            <p>اثر مورد انتظار: {migration.expectedImpact}</p>
            <p>مقصد امن: {migration.targetLabels.join("، ") || "انتخاب نشده"}</p>
            <p>راهبرد credential: <span className="ltr">{migration.credentialStrategies.join(", ") || "در انتظار شبیه‌سازی"}</span></p>
            {migration.highRisk ? <p className="danger">نیازمند تایید پرریسک با plan digest دقیق</p> : null}
            <p>{migration.rollbackFeasible ? "بازگشت در پنجره امن ممکن است." : "بازگشت ساده در این مرحله ممکن نیست."}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export function FailoverProposalList({ proposals }: { proposals: FailoverProposalSummary[] }) {
  return (
    <section dir="rtl" className="managementPanel">
      <h1>پیشنهادهای failover کنترل‌شده</h1>
      {proposals.map((proposal) => (
        <article key={proposal.proposalReference} className="opsCard">
          <h2 className="ltr">{proposal.proposalReference}</h2>
          <p>دلیل امن: {proposal.reason}</p>
          <p>{proposal.sourceUnreachable ? "مبدأ غیرقابل دسترس است؛ فعالیت احتمالی قدیمی صریح باقی می‌ماند." : "مبدأ قابل بررسی است."}</p>
          {proposal.requiresStrongerApproval ? <p className="danger">نیازمند تایید قوی‌تر</p> : null}
        </article>
      ))}
    </section>
  );
}

export function OrphanIdentityList({ orphans }: { orphans: OrphanIdentitySummary[] }) {
  return (
    <section dir="rtl" className="managementPanel">
      <h1>هویت‌های remote یتیم</h1>
      {orphans.map((orphan) => (
        <article key={orphan.orphanReference} className="opsCard">
          <h2 className="ltr">{orphan.orphanReference}</h2>
          <p>مهاجرت: <span className="ltr">{orphan.migrationReference}</span></p>
          <p>{orphan.possibleActive ? "ممکن است هنوز فعال باشد؛ حذف خودکار ممنوع است." : "نیازمند بررسی مالکیت قبل از پاک‌سازی."}</p>
          <p>{orphan.cleanupApproved ? "پاک‌سازی تایید شده" : "در انتظار تایید پاک‌سازی"}</p>
        </article>
      ))}
    </section>
  );
}
