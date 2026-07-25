from __future__ import annotations

from html import escape

SUPPORTED_LOCALE = "fa"

MESSAGES: dict[str, str] = {
    "welcome_new": "سلام! حساب تلگرام شما با موفقیت آماده شد.",
    "welcome_returning": "خوش برگشتید. منوی مشتری آماده است.",
    "menu_title": "از منوی امن زیر استفاده کنید:",
    "restricted": (
        "دسترسی حساب شما در حال حاضر محدود است. لطفاً بعداً از مسیر پشتیبانی امن اقدام کنید."
    ),
    "rate_limited": "لطفاً چند لحظه صبر کنید.",
    "group_ignored": "برای حفظ حریم خصوصی، لطفاً از گفت‌وگوی خصوصی با ربات استفاده کنید.",
    "help": (
        "راهنما: از دکمه‌های ربات برای ورود امن به بخش مشتری، "
        "پروفایل و نشست‌ها استفاده کنید. هیچ رمز یا توکنی در پیام‌های ربات ارسال نمی‌شود."
    ),
    "privacy": (
        "حریم خصوصی: شناسه تلگرام و نام‌های نمایشی لازم برای حساب پردازش می‌شوند. "
        "initData خام مینی‌اپ فقط در سرور اعتبارسنجی می‌شود و "
        "به عنوان راز احراز هویت ذخیره نمی‌شود."
    ),
    "cancel": "عملیات جاری لغو شد.",
    "error": "⚠️ در دریافت اطلاعات مشکلی پیش آمد.\nچند لحظه دیگر دوباره تلاش کنید.",
    "stale": "این دکمه قدیمی است. لطفاً از منوی اصلی دوباره اقدام کنید.",
    "open_app": "باز کردن پنل مشتری (اختیاری)",
    "buy_service": "🛒 خرید سرویس",
    "my_services": "📦 سرویس‌های من",
    "profile": "👤 حساب کاربری",
    "security": "🔐 امنیت و نشست‌ها",
    "wallet": "💰 کیف پول",
    "support": "🎫 پشتیبانی",
    "education": "📚 آموزش اتصال",
    "status": "📡 وضعیت سرویس",
    "help_button": "ℹ️ راهنما",
    "privacy_button": "🔒 حریم خصوصی",
    "refresh": "🔄 بروزرسانی",
}


def normalize_locale(language_code: str | None, supported: tuple[str, ...], default: str) -> str:
    _ = language_code, supported, default
    return SUPPORTED_LOCALE


def t(locale: str, key: str, **kwargs: object) -> str:
    _ = locale
    template = MESSAGES[key]
    safe = {name: escape(str(value), quote=True) for name, value in kwargs.items()}
    return template.format(**safe)
