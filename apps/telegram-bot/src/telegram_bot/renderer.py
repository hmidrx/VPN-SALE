from __future__ import annotations

from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.portal import CustomerProfile, ServiceSummary, Ticket
from telegram_bot.screens import (
    DashboardData,
    RenderedScreen,
    ScreenId,
    fa_number,
    safe_date,
    safe_text,
)


def cb(action: CallbackAction, value: str = "") -> str:
    return BotCallback(action, value).pack()


class ScreenRenderer:
    def render_home(self, data: DashboardData, locale: str) -> RenderedScreen:
        if locale == "en":
            text = (
                f"🚀 VPN Store\n\nHello {safe_text(data.display_name)} 👋\n\n"
                "Buy services, manage subscriptions, wallet, and support from Telegram.\n\n"
                f"Wallet: {data.wallet_balance_minor if data.wallet_balance_minor is not None else 'unavailable'} IRR\n"  # noqa: E501
                f"Active services: {data.active_services if data.active_services is not None else 'unavailable'}\n"  # noqa: E501
                f"Nearest expiry: {safe_date(data.nearest_expiry, locale)}\n"
                f"Open tickets: {data.open_tickets if data.open_tickets is not None else 'unavailable'}"  # noqa: E501
            )
        else:
            wallet = (
                "نامشخص"
                if data.wallet_balance_minor is None
                else f"{fa_number(data.wallet_balance_minor)} تومان"
            )
            active = "نامشخص" if data.active_services is None else fa_number(data.active_services)
            tickets = "نامشخص" if data.open_tickets is None else fa_number(data.open_tickets)
            notice = (
                f"\n\n🔧 اطلاعیه نگهداری: {safe_text(data.maintenance_notice)}"
                if data.maintenance_notice
                else ""
            )
            text = (
                f"🚀 فروشگاه VPN\n\nسلام {safe_text(data.display_name)} عزیز 👋\n\n"
                "حساب شما آماده است. خوش برگشتید.\n\n"
                "از طریق این ربات می‌توانید سرویس بخرید، سرویس‌های خود را مدیریت کنید،\n"
                "کیف پولتان را شارژ کنید و با پشتیبانی در ارتباط باشید.\n\n"
                f"💳 موجودی کیف پول: {wallet}\n"
                f"📦 سرویس‌های فعال: {active}\n"
                f"⏳ نزدیک‌ترین انقضا: {safe_date(data.nearest_expiry, locale)}\n"
                f"🎫 تیکت‌های باز: {tickets}{notice}"
            )
        return RenderedScreen(text, self.home_rows(locale), ScreenId.HOME)

    def home_rows(self, locale: str) -> list[list[dict[str, str]]]:
        labels = [
            ("🛒 Buy service" if locale == "en" else "🛒 خرید سرویس", ScreenId.BUY),
            ("📦 My services" if locale == "en" else "📦 سرویس‌های من", ScreenId.SERVICES),
            ("💳 Wallet" if locale == "en" else "💳 کیف پول", ScreenId.WALLET),
            ("🎁 Discount code" if locale == "en" else "🎁 کد تخفیف", ScreenId.DISCOUNTS),
            ("🎫 Support" if locale == "en" else "🎫 پشتیبانی", ScreenId.SUPPORT),
            ("📚 Education" if locale == "en" else "📚 آموزش اتصال", ScreenId.EDUCATION),
            ("👤 Profile" if locale == "en" else "👤 حساب کاربری", ScreenId.PROFILE),
            ("⚙️ Settings" if locale == "en" else "⚙️ تنظیمات", ScreenId.SETTINGS),
            ("📊 System status" if locale == "en" else "📊 وضعیت سیستم", ScreenId.STATUS),
            ("📣 Announcements" if locale == "en" else "📣 اطلاعیه‌ها", ScreenId.ANNOUNCEMENTS),
        ]
        rows = [
            [
                {"text": a[0], "callback_data": cb(CallbackAction.NAVIGATE, a[1].value)},
                {"text": b[0], "callback_data": cb(CallbackAction.NAVIGATE, b[1].value)},
            ]
            for a, b in zip(labels[0::2], labels[1::2], strict=True)
        ]
        rows.append(
            [
                {
                    "text": "🌐 English" if locale == "fa" else "🌐 فارسی",
                    "callback_data": cb(CallbackAction.NAVIGATE, ScreenId.LANGUAGE.value),
                }
            ]
        )
        return rows

    def nav_rows(self, locale: str) -> list[list[dict[str, str]]]:
        return [
            [
                {
                    "text": "◀️ بازگشت" if locale == "fa" else "◀️ Back",
                    "callback_data": cb(CallbackAction.BACK),
                },
                {
                    "text": "🏠 منوی اصلی" if locale == "fa" else "🏠 Home",
                    "callback_data": cb(CallbackAction.HOME),
                },
            ],
            [
                {
                    "text": "🔄 بروزرسانی" if locale == "fa" else "🔄 Refresh",
                    "callback_data": cb(CallbackAction.REFRESH),
                },
                {
                    "text": "❌ لغو" if locale == "fa" else "❌ Cancel",
                    "callback_data": cb(CallbackAction.CANCEL),
                },
            ],
        ]

    def info(
        self,
        screen: ScreenId,
        locale: str,
        *,
        profile: CustomerProfile | None = None,
        services: list[ServiceSummary] | None = None,
        tickets: list[Ticket] | None = None,
    ) -> RenderedScreen:
        fa: dict[ScreenId, str] = {
            ScreenId.BUY: "🛒 خرید سرویس\n\nفروش سرویس در حال آماده‌سازی است.\nدر نسخه آزمایشی هنوز پرداخت و ساخت واقعی سرویس فعال نشده است.\nمحیط TEST: موفقیت ساختگی نمایش داده نمی‌شود.",  # noqa: E501
            ScreenId.SERVICES: "📦 سرویس‌های من\n\n"
            + (
                "در حال حاضر سرویسی برای این حساب ثبت نشده است."
                if not services
                else "\n".join(
                    f"• {safe_text(s.plan_name)} — {safe_text(s.status)} — انقضا: {safe_date(s.expires_at, 'fa')}"  # noqa: E501
                    for s in services
                )
            ),
            ScreenId.WALLET: "💳 کیف پول\n\nموجودی فعلی: ۰ تومان\nدرگاه پرداخت محیط آزمایشی هنوز فعال نشده است.\n\nتراکنش‌های اخیر:\n• فعلاً تراکنشی نمایش داده نمی‌شود.",  # noqa: E501
            ScreenId.DISCOUNTS: "🎁 کد تخفیف\n\nامکان ثبت کد تخفیف به‌زودی داخل ربات فعال می‌شود.",
            ScreenId.SUPPORT: "🎫 پشتیبانی\n\n- ایجاد تیکت جدید\n- تیکت‌های من\n- سوالات متداول",
            ScreenId.EDUCATION: "📚 آموزش اتصال\n\n- اندروید\n- آیفون و آیپد\n- ویندوز\n- مک\n- لینوکس",  # noqa: E501
            ScreenId.STATUS: "📊 وضعیت سیستم\n\nهمه بخش‌های اصلی در حالت آزمایشی آماده هستند.",
            ScreenId.ANNOUNCEMENTS: "📣 اطلاعیه‌ها\n\nدر حال حاضر اطلاعیه جدیدی وجود ندارد.",
            ScreenId.PRIVACY: "🔒 حریم خصوصی\n\nفقط اطلاعات لازم برای ارائه سرویس پردازش می‌شود.",
            ScreenId.HELP: "ℹ️ راهنما\n\nاز دکمه‌های همین ربات برای کار با فروشگاه استفاده کنید.",
        }
        if screen == ScreenId.PROFILE and profile is not None:
            fa[screen] = (
                f"👤 حساب کاربری\n\n- نام نمایشی: {safe_text(profile.display_name)}\n- وضعیت اتصال تلگرام: {'فعال' if profile.telegram_linked else 'غیرفعال'}\n- تاریخ عضویت: {safe_date(profile.created_at, 'fa')}\n- زبان انتخابی: {safe_text(profile.language)}"  # noqa: E501
            )
        if screen == ScreenId.SERVICES and services:
            rows = [
                [
                    {
                        "text": safe_text(s.plan_name),
                        "callback_data": cb(CallbackAction.OPEN_SERVICE, s.ref),
                    }
                ]
                for s in services[:4]
            ]
            rows.extend(self.nav_rows(locale))
            return RenderedScreen(fa[screen], rows, screen)
        if screen == ScreenId.WALLET:
            rows = [
                [{"text": "افزایش موجودی", "callback_data": cb(CallbackAction.TOP_UP)}],
                *self.nav_rows(locale),
            ]
            return RenderedScreen(fa[screen], rows, screen)
        if screen == ScreenId.SETTINGS:
            rows = [
                [
                    {
                        "text": "🌐 زبان",
                        "callback_data": cb(CallbackAction.NAVIGATE, ScreenId.LANGUAGE.value),
                    },
                    {
                        "text": "🔒 حریم خصوصی",
                        "callback_data": cb(CallbackAction.NAVIGATE, ScreenId.PRIVACY.value),
                    },
                ],
                [
                    {"text": "🔔 اعلان‌ها", "callback_data": cb(CallbackAction.RETRY)},
                    {
                        "text": "🌐 باز کردن نسخه وب",
                        "callback_data": cb(CallbackAction.OPEN_WEB_APP),
                    },
                ],
                *self.nav_rows(locale),
            ]
            return RenderedScreen(
                "⚙️ تنظیمات\n\n- زبان\n- اعلان‌ها\n- حریم خصوصی\n- نشست‌ها\n- باز کردن نسخه وب، اختیاری",  # noqa: E501
                rows,
                screen,
            )
        if screen == ScreenId.LANGUAGE:
            return RenderedScreen(
                "🌐 زبان را انتخاب کنید",
                [
                    [
                        {"text": "فارسی", "callback_data": cb(CallbackAction.SET_LANGUAGE, "fa")},
                        {"text": "English", "callback_data": cb(CallbackAction.SET_LANGUAGE, "en")},
                    ],
                    *self.nav_rows(locale),
                ],
                screen,
            )
        return RenderedScreen(
            fa.get(screen, "⚠️ این بخش در حال آماده‌سازی است."), self.nav_rows(locale), screen
        )
