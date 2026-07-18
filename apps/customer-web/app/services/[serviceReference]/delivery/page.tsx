const formats = ["لینک تکی", "QR محلی", "اشتراک پایدار", "Mihomo", "Clash قدیمی در صورت سازگاری", "sing-box"];

export default function CustomerDeliveryPage() {
  return <main dir="rtl"><h1>تحویل امن سرویس</h1><p>برای نمایش credential باید عمداً دکمه آشکارسازی را بزنید؛ داده حساس در localStorage یا URL قرار نمی‌گیرد.</p><ul>{formats.map((format) => <li key={format}>{format}</li>)}</ul><p dir="ltr">technical values render left-to-right</p></main>;
}
