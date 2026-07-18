export default async function Page({ params }: { params: Promise<{ releaseReference: string }> }): Promise<React.ReactElement> {
  const { releaseReference } = await params;
  return <main dir="rtl" className="admin-page"><h1>rollback انتشار <code dir="ltr">{releaseReference}</code></h1><p>وضعیت‌های صریح <code dir="ltr">NOT_RUN</code>، <code dir="ltr">BLOCKED</code>، <code dir="ltr">PAUSED</code> و شواهد زمان‌دار immutable نمایش داده می‌شوند. این UI هیچ دکمه‌ای برای دور زدن حفاظت محیط تولید یا اجرای فرمان دلخواه ندارد.</p><ul><li>تأیید نسخه stale با خطای کنترل‌شده متوقف می‌شود.</li><li>Rollback مالی/سرویس حذف مخرب انجام نمی‌دهد و فقط reconciliation/manual review می‌سازد.</li><li>انتشار فاز بعدی هرگز از state فرانت‌اند انجام نمی‌شود.</li></ul></main>;
}
