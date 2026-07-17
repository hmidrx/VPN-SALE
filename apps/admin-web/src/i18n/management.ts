export const fa = {
  nav: { overview: "نمای کلی", admins: "مدیران", roles: "نقش‌ها", permissions: "مجوزها", customers: "مشتریان", sessions: "نشست‌ها", audit: "لاگ حسابرسی", security: "مرکز امنیت", personal: "امنیت شخصی" },
  states: { forbidden: "شما مجوز دسترسی به این بخش را ندارید.", unavailable: "سرویس مدیریت موقتاً در دسترس نیست.", error: "درخواست مدیریت با خطای ایمن متوقف شد." },
  invitation: { warning: "توکن دعوت فقط همین یک بار نمایش داده می‌شود؛ آن را در URL یا ذخیره‌ساز مرورگر قرار ندهید.", acknowledged: "توکن را امن ذخیره کردم" },
  actions: { view: "مشاهده", invite: "دعوت مدیر", copy: "کپی", confirm: "تأیید", revoke: "لغو نشست", revokeAll: "لغو همه", suspend: "تعلیق", activate: "فعال‌سازی", acknowledge: "تصدیق", resolve: "حل کردن" },
  errors: { forbidden: "دسترسی مجاز نیست", final_super_admin: "آخرین مسیر Super Admin فعال قابل حذف یا غیرفعال‌سازی نیست.", unsafe_self_change: "عملیات ناامن روی حساب فعلی مجاز نیست.", protected_role: "نقش داخلی محافظت‌شده است.", service_unavailable: "سرویس در دسترس نیست.", unknown: "خطای امن و کنترل‌شده رخ داد." }
} as const;
export const en = { nav: { overview: "Overview", admins: "Administrators", roles: "Roles", permissions: "Permissions", customers: "Customers", sessions: "Sessions", audit: "Audit logs", security: "Security center", personal: "Personal security" } } as const;
export type ManagementMessageKey = keyof typeof fa;
