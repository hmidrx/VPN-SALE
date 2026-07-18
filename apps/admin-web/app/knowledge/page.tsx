const blocks = ["HEADING", "PARAGRAPH", "IMAGE", "VIDEO", "DOWNLOAD", "WARNING", "FAQ", "TROUBLESHOOTING_FLOW"];
export default function KnowledgeAdminPage(): React.ReactElement {
  return <main dir="rtl"><h1>کنسول دانش و آموزش</h1><p>مدیریت draft، اعتبارسنجی، preview کوتاه‌مدت، بازبینی، زمان‌بندی، انتشار، rollback، رسانه آموزشی، FAQ و عیب‌یابی.</p><section aria-label="ویرایشگر بلوکی"><h2>بلوک‌های ثبت‌شده امن</h2><ul>{blocks.map((block) => <li key={block}>{block}</li>)}</ul></section><p>ویرایشگر اصلی raw JSON نیست و هیچ HTML، JavaScript، CSS یا قالب اجرایی نمی‌پذیرد.</p></main>;
}
