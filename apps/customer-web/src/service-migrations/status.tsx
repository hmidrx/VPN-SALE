export interface SafeMigrationStatus {
  serviceReference: string;
  status: "NONE" | "LOADING" | "ERROR" | "UNAUTHORIZED" | "SCHEDULED" | "IN_PROGRESS" | "COMPLETED";
  expectedImpact: string;
  configurationRefreshRequired: boolean;
  deliveryReady: boolean;
  safeLocationLabel?: string;
}

export function isOpaqueServiceReference(value: string): boolean {
  return /^(SVC|svc)-[A-Za-z0-9][A-Za-z0-9_-]{2,63}$/.test(value);
}

export function ServiceMigrationNotice({ status }: { status: SafeMigrationStatus }) {
  const stateText: Record<SafeMigrationStatus["status"], string> = {
    NONE: "مهاجرت فعالی وجود ندارد.",
    LOADING: "در حال دریافت وضعیت مهاجرت…",
    ERROR: "وضعیت مهاجرت در دسترس نیست؛ لطفاً از مسیر پشتیبانی پیگیری کنید.",
    UNAUTHORIZED: "شما به وضعیت مهاجرت این سرویس دسترسی ندارید.",
    SCHEDULED: "مهاجرت سرویس زمان‌بندی شده است.",
    IN_PROGRESS: "مهاجرت سرویس در حال انجام است.",
    COMPLETED: "مهاجرت سرویس تکمیل شده است.",
  };
  return (
    <section dir="rtl" aria-label="وضعیت مهاجرت سرویس" data-migration-status={status.status}>
      <h1>وضعیت مهاجرت سرویس</h1>
      <p>وضعیت: <strong>{stateText[status.status]}</strong></p>
      <p>{status.expectedImpact}</p>
      <p>{status.deliveryReady ? "تحویل فعلی در دسترس است." : "تحویل پس از تایید مقصد آماده می‌شود."}</p>
      {status.safeLocationLabel ? <p>موقعیت امن مقصد: {status.safeLocationLabel}</p> : null}
      {status.configurationRefreshRequired ? <p>پس از تکمیل، برنامه خود را به‌روزرسانی کنید.</p> : null}
      <a href="/support">ارتباط با پشتیبانی</a>
    </section>
  );
}
