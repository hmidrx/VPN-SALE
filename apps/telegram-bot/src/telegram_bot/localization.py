from __future__ import annotations

from html import escape

MESSAGES: dict[str, dict[str, str]] = {
    "fa": {
        "welcome_new": "سلام! حساب تلگرام شما با موفقیت آماده شد.",
        "welcome_returning": "خوش برگشتید. منوی مشتری آماده است.",
        "menu_title": "از منوی امن زیر استفاده کنید:",
        "restricted": (
            "دسترسی حساب شما در حال حاضر محدود است. " "لطفاً بعداً از مسیر پشتیبانی امن اقدام کنید."
        ),
        "rate_limited": "درخواست‌ها بیش از حد مجاز است. کمی بعد دوباره تلاش کنید.",
        "group_ignored": "برای حفظ حریم خصوصی، لطفاً از گفت‌وگوی خصوصی با ربات استفاده کنید.",
        "help": (
            "راهنما: از دکمه‌های Mini App برای ورود امن به بخش مشتری، "
            "پروفایل و نشست‌ها استفاده کنید. هیچ رمز یا توکنی در پیام‌های ربات ارسال نمی‌شود."
        ),
        "privacy": (
            "حریم خصوصی: شناسه تلگرام و نام‌های نمایشی لازم برای حساب پردازش می‌شوند. "
            "initData خام Mini App فقط در سرور اعتبارسنجی می‌شود و "
            "به عنوان راز احراز هویت ذخیره نمی‌شود."
        ),
        "language": "زبان پیش‌فرض فارسی است. English برای توسعه بعدی آماده شده است.",
        "cancel": "عملیات جاری لغو شد.",
        "error": "درخواست با خطای موقت روبه‌رو شد. لطفاً بعداً دوباره تلاش کنید.",
        "open_app": "باز کردن پنل مشتری",
        "profile": "پروفایل",
        "security": "نشست‌ها و امنیت",
        "help_button": "راهنما",
        "language_button": "زبان",
        "privacy_button": "حریم خصوصی",
        "refresh": "به‌روزرسانی منو",
    },
    "en": {
        "welcome_new": "Hello! Your Telegram account is ready.",
        "welcome_returning": "Welcome back. Your customer menu is ready.",
        "menu_title": "Use the secure customer menu below:",
        "restricted": "Your account access is currently restricted.",
        "rate_limited": "Too many requests. Please try again later.",
        "group_ignored": "For privacy, please use a private chat with the bot.",
        "help": (
            "Help: use Mini App buttons for customer home, profile, and sessions. "
            "No credentials or tokens are sent in bot messages."
        ),
        "privacy": (
            "Privacy: Telegram identity fields needed for the account are processed. "
            "Raw Mini App initData is verified server-side and not stored "
            "as an authentication secret."
        ),
        "language": "Persian is the default. English is prepared for later expansion.",
        "cancel": "Current operation cancelled.",
        "error": "Temporary error. Please try again later.",
        "open_app": "Open customer app",
        "profile": "Profile",
        "security": "Sessions & security",
        "help_button": "Help",
        "language_button": "Language",
        "privacy_button": "Privacy",
        "refresh": "Refresh menu",
    },
}


def normalize_locale(language_code: str | None, supported: tuple[str, ...], default: str) -> str:
    if not language_code:
        return default
    normalized = language_code.split("-", 1)[0].lower()
    return normalized if normalized in supported else default


def t(locale: str, key: str, **kwargs: object) -> str:
    catalog = MESSAGES.get(locale, MESSAGES["fa"])
    template = catalog.get(key, MESSAGES["fa"].get(key, key))
    safe = {name: escape(str(value), quote=True) for name, value in kwargs.items()}
    return template.format(**safe)
