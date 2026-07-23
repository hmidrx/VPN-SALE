from __future__ import annotations

from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.formatting import format_toman
from telegram_bot.portal import CustomerProfile, NotificationPreferences, ServiceSummary, Ticket
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
        _ = locale
        wallet = format_toman(data.wallet_balance_minor)
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
            f"⏳ نزدیک‌ترین انقضا: {safe_date(data.nearest_expiry)}\n"
            f"🎫 تیکت‌های باز: {tickets}{notice}"
        )
        return RenderedScreen(text, self.home_rows(locale), ScreenId.HOME)

    def home_rows(self, locale: str) -> list[list[dict[str, str]]]:
        _ = locale
        labels = [
            ("🛒 خرید سرویس", ScreenId.BUY),
            ("📦 سرویس‌های من", ScreenId.SERVICES),
            ("💳 کیف پول", ScreenId.WALLET),
            ("🎁 کد تخفیف", ScreenId.DISCOUNTS),
            ("🎫 پشتیبانی", ScreenId.SUPPORT),
            ("📚 آموزش اتصال", ScreenId.EDUCATION),
            ("👤 حساب کاربری", ScreenId.PROFILE),
            ("⚙️ تنظیمات", ScreenId.SETTINGS),
            ("📊 وضعیت سیستم", ScreenId.STATUS),
            ("📣 اطلاعیه‌ها", ScreenId.ANNOUNCEMENTS),
        ]
        return [
            [
                {"text": a[0], "callback_data": cb(CallbackAction.NAVIGATE, a[1].value)},
                {"text": b[0], "callback_data": cb(CallbackAction.NAVIGATE, b[1].value)},
            ]
            for a, b in zip(labels[0::2], labels[1::2], strict=True)
        ]

    def nav_rows(self, locale: str) -> list[list[dict[str, str]]]:
        _ = locale
        return [
            [
                {"text": "◀️ بازگشت", "callback_data": cb(CallbackAction.BACK)},
                {"text": "🏠 منوی اصلی", "callback_data": cb(CallbackAction.HOME)},
            ],
            [
                {"text": "🔄 بروزرسانی", "callback_data": cb(CallbackAction.REFRESH)},
                {"text": "❌ لغو", "callback_data": cb(CallbackAction.CANCEL)},
            ],
        ]

    def notifications(
        self,
        locale: str,
        preferences: NotificationPreferences,
        *,
        mutation_error: bool = False,
    ) -> RenderedScreen:
        _ = locale
        labels = (
            ("service_expiry_enabled", "پایان اعتبار سرویس"),
            ("low_traffic_enabled", "کمبود حجم"),
            ("payment_enabled", "پرداخت‌ها"),
            ("support_reply_enabled", "پاسخ پشتیبانی"),
            ("announcements_enabled", "اطلاعیه‌های مهم"),
        )
        state = {
            "service_expiry_enabled": preferences.service_expiry_enabled,
            "low_traffic_enabled": preferences.low_traffic_enabled,
            "payment_enabled": preferences.payment_enabled,
            "support_reply_enabled": preferences.support_reply_enabled,
            "announcements_enabled": preferences.announcements_enabled,
        }
        prefix = "⚠️ تغییر تنظیمات ذخیره نشد.\nلطفاً دوباره تلاش کنید.\n\n" if mutation_error else ""
        text = (
            f"{prefix}🔔 تنظیمات اعلان‌ها\n\n"
            "اعلان‌هایی را که مایل به دریافت آن‌ها هستید مدیریت کنید.\n\n"
            f"{'✅' if preferences.service_expiry_enabled else '❌'} پایان اعتبار سرویس\n"
            f"{'✅' if preferences.low_traffic_enabled else '❌'} کمبود حجم\n"
            f"{'✅' if preferences.payment_enabled else '❌'} پرداخت‌ها و تراکنش‌ها\n"
            f"{'✅' if preferences.support_reply_enabled else '❌'} پاسخ پشتیبانی\n"
            f"{'✅' if preferences.announcements_enabled else '❌'} اطلاعیه‌های مهم"
        )
        buttons = [
            {
                "text": f"{'✅' if state[key] else '❌'} {label}",
                "callback_data": cb(CallbackAction.TOGGLE_NOTIFICATION, key),
            }
            for key, label in labels
        ]
        rows = [
            [buttons[0], buttons[1]],
            [buttons[2], buttons[3]],
            [buttons[4]],
            *self.nav_rows(locale)[:2],
        ]
        return RenderedScreen(text, rows, ScreenId.NOTIFICATIONS)

    def notification_error(self, locale: str) -> RenderedScreen:
        _ = locale
        return RenderedScreen(
            "⚠️ در دریافت تنظیمات اعلان‌ها مشکلی پیش آمد.\nچند لحظه دیگر دوباره تلاش کنید.",
            [
                [{"text": "🔄 تلاش دوباره", "callback_data": cb(CallbackAction.RETRY)}],
                [{"text": "🏠 منوی اصلی", "callback_data": cb(CallbackAction.HOME)}],
            ],
            ScreenId.NOTIFICATIONS,
        )

    def info(
        self,
        screen: ScreenId,
        locale: str,
        *,
        profile: CustomerProfile | None = None,
        services: list[ServiceSummary] | None = None,
        tickets: list[Ticket] | None = None,
        notification_preferences: NotificationPreferences | None = None,
        notification_error: bool = False,
        mutation_error: bool = False,
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
                f"👤 حساب کاربری\n\n- نام نمایشی: {safe_text(profile.display_name)}\n"
                f"- وضعیت اتصال تلگرام: {'فعال' if profile.telegram_linked else 'غیرفعال'}\n"
                f"- وضعیت حساب: {safe_text(profile.account_state.value)}\n"
                f"- تاریخ عضویت: {safe_date(profile.created_at)}"
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
                        "text": "🔒 حریم خصوصی",
                        "callback_data": cb(CallbackAction.NAVIGATE, ScreenId.PRIVACY.value),
                    },
                    {
                        "text": "🔔 اعلان‌ها",
                        "callback_data": cb(CallbackAction.NAVIGATE, ScreenId.NOTIFICATIONS.value),
                    },
                ],
                [
                    {
                        "text": "🌐 باز کردن نسخه وب",
                        "callback_data": cb(CallbackAction.OPEN_WEB_APP),
                    }
                ],
                *self.nav_rows(locale),
            ]
            return RenderedScreen(
                (
                    "⚙️ تنظیمات\n\n"
                    "برای مدیریت هر بخش از دکمه همان بخش استفاده کنید.\n\n"
                    "• اعلان‌ها\n• حریم خصوصی\n• نسخه وب، اختیاری"
                ),
                rows,
                screen,
            )
        if screen == ScreenId.LANGUAGE:
            return RenderedScreen(
                "این دکمه قدیمی است. لطفاً از منوی اصلی دوباره اقدام کنید.",
                [[{"text": "🏠 منوی اصلی", "callback_data": cb(CallbackAction.HOME)}]],
                ScreenId.HOME,
            )
        return RenderedScreen(
            fa.get(screen, "⚠️ این بخش در حال آماده‌سازی است."), self.nav_rows(locale), screen
        )
