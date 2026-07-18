const rows = [
  ["درخواست‌های آماده", "READY_FOR_FULFILLMENT", "مصرف دقیقاً یک‌بار"],
  ["سرویس‌های در حال تخصیص", "PENDING_ALLOCATION", "انتخاب هدف سمت سرور"],
  ["رزرو ظرفیت", "ACTIVE_RESERVATION", "بدون عبور از سقف"],
  ["بازبینی دستی", "MANUAL_REVIEW", "نیازمند تأیید اپراتور"],
];

export function ServiceConsole({ title, focus }: { title: string; focus: string }): React.ReactElement {
  return (
    <main className="mgmt-main" dir="rtl">
      <section className="mgmt-top">
        <div>
          <p className="eyebrow">Milestone 6-B1</p>
          <h1>{title}</h1>
          <p className="muted">{focus}</p>
        </div>
        <a className="btn secondary" href="/management/security-events">مرکز امنیت</a>
      </section>
      <section className="cards" aria-label="شاخص‌های عملیات سرویس">
        <article className="panel metric"><span>فعال‌سازی کامل</span><strong className="tech">ALL_REQUIRED</strong><small>بدون موفقیت خوش‌بینانه</small></article>
        <article className="panel metric"><span>حریم خصوصی</span><strong>ایمن</strong><small>بدون پنل، اینباند، اعتبارنامه یا لینک اشتراک</small></article>
        <article className="panel metric"><span>هم‌روندی</span><strong>رزرو</strong><small>ظرفیت با قفل تراکنشی نگه‌داری می‌شود</small></article>
      </section>
      <section className="panel">
        <h2>صف عملیات</h2>
        <div className="filters" role="search" aria-label="فیلترهای محدود سمت سرور">
          <input aria-label="جستجوی مرجع عمومی سرویس" placeholder="مرجع عمومی سرویس" />
          <select aria-label="وضعیت"><option>همه وضعیت‌ها</option><option>PROVISIONING_FAILED</option><option>MANUAL_REVIEW</option></select>
          <button className="btn secondary" type="button">اعمال فیلتر</button>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>نام</th><th>کد فنی</th><th>کنترل</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={row[1]}><td data-label="نام">{row[0]}</td><td data-label="کد فنی" className="tech">{row[1]}</td><td data-label="کنترل">{row[2]}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
      <section className="panel confirm" aria-label="تأیید عملیات حساس">
        <strong>تأیید دقیق برای تکرار، ترمیم یا جبران</strong>
        <label>دلیل ایمن اپراتور<textarea placeholder="بدون راز، لینک، شناسه پنل یا داده پرداخت" /></label>
        <button className="btn danger" type="button">ثبت برای بازبینی؛ اجرای خودکار انجام نمی‌شود</button>
      </section>
    </main>
  );
}
