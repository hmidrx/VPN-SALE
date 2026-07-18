const fields = ["نشانی عمومی", "پورت", "SNI", "ALPN", "کلید عمومی REALITY", "مسیر WebSocket/XHTTP", "serviceName gRPC", "قالب امن توضیح"];

export default function DeliveryProfilesPage() {
  return <main dir="rtl" className="management-page"><h1>پروفایل‌های تحویل</h1><p>ویرایشگر تایپ‌شده پروفایل تحویل، انتشار نسخه immutable، پیش‌نمایش با credential مصنوعی و بازگردانی کنترل‌شده.</p><section aria-label="فیلدهای پویا"><h2>فیلدهای پویا</h2><ul>{fields.map((field) => <li key={field}><code dir="ltr">{field}</code></li>)}</ul></section><section><h2>محدودیت‌های امنیتی</h2><p>لینک‌های پنل منبع معتبر نیستند، کلید خصوصی REALITY و credential واقعی در پیش‌نمایش عادی نشان داده نمی‌شود.</p></section></main>;
}
