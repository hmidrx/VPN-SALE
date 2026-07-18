const cards = [
  ['نمای کلی ناوگان', 'سلامت کنترل‌پلین، ظرفیت، نگهداری و تخلیه بدون نمایش شناسه‌های زیرساختی.'],
  ['ظرفیت و پیش‌بینی', 'هد‌روم فعلی، رزروهای در انتظار، مصرف دو‌فعال و پیش‌بینی قطعی‌گرایانه.'],
  ['نگهداری و Drain', 'پنجره‌های نگهداری، مسدودسازی تخصیص و پیشرفت تخلیه کنترل‌شده.'],
  ['Failover و Recovery', 'پیشنهادها فقط با شواهد، تأیید جداگانه و اجرای کنترل‌شده از مسیر مهاجرت.'],
  ['Bulk و Runbook', 'عملیات allowlist شده، snapshot ثابت، dry-run، تأیید و گزارش آیتمی.'],
]

export default function FleetPage() {
  return (
    <main dir="rtl" className="mx-auto flex max-w-7xl flex-col gap-6 p-6 text-slate-100">
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-xl">
        <p className="text-sm text-cyan-300">Milestone 6-D2</p>
        <h1 className="mt-2 text-3xl font-bold">کنسول عملیات ناوگان</h1>
        <p className="mt-3 max-w-3xl leading-8 text-slate-300">
          این کنسول داده واقعی APIهای مدیریت ناوگان را نمایش می‌دهد و هیچ وضعیت خوش‌بینانه، payload خام، URL پنل، شناسه node/inbound یا credential را در DOM یا storage قرار نمی‌دهد.
        </p>
      </section>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {cards.map(([title, body]) => (
          <article key={title} className="rounded-2xl border border-slate-700 bg-slate-950 p-5">
            <h2 className="text-xl font-semibold">{title}</h2>
            <p className="mt-3 leading-7 text-slate-300">{body}</p>
            <p className="mt-4 text-sm text-amber-300">سلامت مشتری end-to-end ادعا نمی‌شود؛ فقط کنترل‌پلین/گزارش ارائه‌دهنده نمایش داده می‌شود.</p>
          </article>
        ))}
      </section>
    </main>
  )
}
