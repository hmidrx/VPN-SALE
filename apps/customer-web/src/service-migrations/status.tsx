export interface SafeMigrationStatus {
  serviceReference: string;
  status: string;
  expectedImpact: string;
  configurationRefreshRequired: boolean;
  deliveryReady: boolean;
  safeLocationLabel?: string;
}

export function ServiceMigrationNotice({ status }: { status: SafeMigrationStatus }) {
  return (
    <section dir="rtl" aria-label="وضعیت مهاجرت سرویس">
      <h1>وضعیت مهاجرت سرویس</h1>
      <p>وضعیت: <strong>{status.status}</strong></p>
      <p>{status.expectedImpact}</p>
      <p>{status.deliveryReady ? "تحویل فعلی در دسترس است." : "تحویل پس از تایید مقصد آماده می‌شود."}</p>
      {status.configurationRefreshRequired ? <p>پس از تکمیل، برنامه خود را به‌روزرسانی کنید.</p> : null}
    </section>
  );
}
