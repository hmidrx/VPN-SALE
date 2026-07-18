const gates = ["NOT_RUN", "BLOCKED", "PASSED", "EXPIRED"];
export default function ProductionReleasesPage(): React.ReactElement {
  return <main dir="rtl" className="admin-page"><h1>کنسول انتشار کنترل‌شده تولید</h1><p>این صفحه فقط برنامه‌های انتشار، شواهد سانیتایزشده و وضعیت‌های operator-only را نمایش می‌دهد؛ هیچ راز، endpoint کامل، فهرست مشتری یا فرمان shell وجود ندارد.</p><section><h2>گیت‌های اصلی</h2><ul>{gates.map((gate) => <li key={gate}><code dir="ltr">{gate}</code></li>)}</ul></section><section><h2>عملیات پرخطر</h2><p>استقرار، شروع canary، پیشروی، resume و rollback نیازمند workflow_dispatch محافظت‌شده، تأیید تایپی دقیق و جداسازی تأییدکننده‌ها است.</p><a href="/management/releases/production/prod-rel-7b-ci">مشاهده نمونه CI-safe</a></section></main>;
}
