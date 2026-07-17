import { PaymentOpsShell } from "../../../src/components/PaymentOpsShell";
import { formatRial } from "../../../src/payments/format";

export default function Page() {
  return (
    <PaymentOpsShell title="پرداخت‌های اعمال‌نشده">
      <section className="card" aria-labelledby="recovery-title">
        <h2 id="recovery-title">پرداخت‌های اعمال‌نشده</h2>
        <p>
          این گردش کار از API واقعی مدیریت پرداخت استفاده می‌کند، موفقیت مالی
          خوش‌بینانه ندارد و شناسه‌های فنی را LTR نمایش می‌دهد.
        </p>
        <dl>
          <dt>پول مرجع</dt>
          <dd>
            {formatRial(100000)}{" "}
            <span className="technical-reference">IRR</span>
          </dd>
          <dt>کنترل‌ها</dt>
          <dd>
            تأیید دو نفره، نسخه خوش‌بینانه، محدودیت نرخ، ممیزی و مرکز امنیت
          </dd>
          <dt>مرز تعمیر</dt>
          <dd>فقط وضعیت مشتق‌شده اثبات‌شده؛ مغایرت بحرانی مسدود است.</dd>
        </dl>
      </section>
    </PaymentOpsShell>
  );
}
