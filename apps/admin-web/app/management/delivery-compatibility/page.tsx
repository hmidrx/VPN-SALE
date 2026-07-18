const renderers = ["VLESS URI", "VMess compatibility URI", "Trojan URI", "Shadowsocks SIP002", "Mihomo YAML", "Legacy Clash-compatible", "sing-box JSON"];

export default function DeliveryCompatibilityPage() {
  return <main dir="rtl" className="management-page"><h1>سازگاری تحویل</h1><p>ماتریس سازگاری نسخه‌بندی‌شده برای جلوگیری از تبدیل ناقص یا کاهش امنیت.</p><ul>{renderers.map((renderer) => <li key={renderer}><span dir="ltr">{renderer}</span></li>)}</ul><p>Legacy Clash از VLESS، REALITY و XHTTP پشتیبانی اعلام‌شده ندارد و باید خطای سازگاری بگیرد.</p></main>;
}
