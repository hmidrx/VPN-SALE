from __future__ import annotations

from typing import cast

from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.formatting import format_toman
from telegram_bot.menu import runtime_menu_rows
from telegram_bot.portal import (
    CustomerProfile,
    NotificationPreferences,
    ServiceSummary,
    Ticket,
    WalletTransaction,
)
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
    def render_home(
        self,
        data: DashboardData,
        locale: str,
        runtime: dict[str, object] | None = None,
    ) -> RenderedScreen:
        wallet = format_toman(data.wallet_balance_minor)
        active = (
            "نامشخص"
            if data.active_services is None
            else fa_number(data.active_services)
        )
        notice = (
            f"\n\n🔧 اطلاعیه نگهداری: {safe_text(data.maintenance_notice)}"
            if data.maintenance_notice
            else ""
        )
        brand_value = runtime.get("brand") if runtime else None
        brand = (
            cast(dict[str, object], brand_value)
            if isinstance(brand_value, dict)
            else {}
        )
        short_name_value = brand.get("short_name")
        short_name = (
            short_name_value if isinstance(short_name_value, str) else "VPN-SALE"
        )
        tagline_value = brand.get("tagline")
        tagline_map = (
            cast(dict[str, object], tagline_value)
            if isinstance(tagline_value, dict)
            else {}
        )
        tagline = tagline_map.get(locale)
        intro = safe_text(
            tagline
            if isinstance(tagline, str)
            else f"حساب شما در {short_name} آماده است."
        )
        text = (
            f"◈ {safe_text(short_name)}  |  مرکز کنترل\n"
            f"سلام {safe_text(data.display_name)} عزیز\n"
            f"{intro}\n\n"
            f"موجودی کیف پول  ·  {wallet}\n"
            f"سرویس‌های فعال  ·  {active}\n"
            f"نزدیک‌ترین انقضا  ·  {safe_date(data.nearest_expiry)}{notice}\n\n"
            "یکی از کارهای زیر را انتخاب کنید:"
        )
        menu_value = runtime.get("telegram_menu") if runtime else None
        menu_items = (
            [
                cast(dict[str, object], item)
                for item in cast(list[object], menu_value)
                if isinstance(item, dict)
            ]
            if isinstance(menu_value, list)
            else []
        )
        rows = runtime_menu_rows(menu_items, locale)
        return RenderedScreen(text, rows or self.home_rows(locale), ScreenId.HOME)

    def home_rows(self, locale: str) -> list[list[dict[str, str]]]:
        _ = locale

        def nav(text: str, screen: ScreenId) -> dict[str, str]:
            return {
                "text": text,
                "callback_data": cb(CallbackAction.NAVIGATE, screen.value),
            }

        return [
            [
                nav("🛒 خرید سرویس", ScreenId.BUY),
                nav("📦 سرویس‌های من", ScreenId.SERVICES),
            ],
            [
                nav("💳 کیف پول", ScreenId.WALLET),
                {
                    "text": "➕ افزایش موجودی",
                    "callback_data": cb(CallbackAction.TOP_UP),
                },
            ],
            [nav("🎫 پشتیبانی", ScreenId.SUPPORT), nav("👤 حساب من", ScreenId.PROFILE)],
            [
                nav("🔔 اعلان‌ها", ScreenId.NOTIFICATIONS),
                {
                    "text": "🌐 باز کردن مینی‌اپ",
                    "callback_data": cb(CallbackAction.OPEN_WEB_APP),
                },
            ],
        ]

    def nav_rows(
        self, locale: str, *, refresh: bool = False
    ) -> list[list[dict[str, str]]]:
        _ = locale
        rows = [
            [
                {"text": "◀️ بازگشت", "callback_data": cb(CallbackAction.BACK)},
                {"text": "🏠 منوی اصلی", "callback_data": cb(CallbackAction.HOME)},
            ],
        ]
        if refresh:
            rows.insert(
                0,
                [{"text": "🔄 بروزرسانی", "callback_data": cb(CallbackAction.REFRESH)}],
            )
        return rows

    def notifications(
        self,
        locale: str,
        preferences: NotificationPreferences,
        *,
        mutation_error: bool = False,
        wallet_balance: int | None = None,
        transactions: list[WalletTransaction] | None = None,
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
        prefix = (
            "⚠️ تغییر تنظیمات ذخیره نشد.\nلطفاً دوباره تلاش کنید.\n\n"
            if mutation_error
            else ""
        )
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
        wallet_balance: int | None = None,
        transactions: list[WalletTransaction] | None = None,
    ) -> RenderedScreen:
        fa: dict[ScreenId, str] = {
            ScreenId.BUY: "🛒 خرید سرویس",
            ScreenId.SERVICES: "📦 سرویس‌های من\n\n"
            + (
                "در حال حاضر سرویسی برای این حساب ثبت نشده است."
                if not services
                else "\n".join(
                    f"• {safe_text(s.plan_name)} — {safe_text({'active': 'فعال', 'expired': 'پایان‌یافته', 'pending': 'در حال آماده‌سازی', 'failed': 'ناموفق'}.get(s.status.lower(), 'در حال بررسی'))} — انقضا: {safe_date(s.expires_at, 'fa')}"  # noqa: E501
                    for s in services
                )
            ),
            ScreenId.WALLET: "💳 کیف پول",
            ScreenId.DISCOUNTS: "🎁 کد تخفیف\n\nامکان ثبت کد تخفیف به‌زودی داخل ربات فعال می‌شود.",
            ScreenId.SUPPORT: "🎫 پشتیبانی\n\n- ایجاد تیکت جدید\n- تیکت‌های من\n- سوالات متداول",
            ScreenId.EDUCATION: "📚 آموزش اتصال\n\n- اندروید\n- آیفون و آیپد\n- ویندوز\n- مک\n- لینوکس",  # noqa: E501
            ScreenId.STATUS: "📊 وضعیت سرویس\n\nوضعیت عمومی در مینی‌اپ در دسترس است.",
            ScreenId.ANNOUNCEMENTS: "📣 اطلاعیه‌ها\n\nدر حال حاضر اطلاعیه جدیدی وجود ندارد.",
            ScreenId.PRIVACY: "🔒 حریم خصوصی\n\nفقط اطلاعات لازم برای ارائه سرویس پردازش می‌شود.",
            ScreenId.HELP: "ℹ️ راهنما\n\nاز دکمه‌های همین ربات برای کار با فروشگاه استفاده کنید.",
        }
        if screen == ScreenId.PROFILE and profile is not None:
            account_label = {
                "ACTIVE": "فعال",
                "PENDING": "در حال تکمیل",
                "SUSPENDED": "محدود",
            }.get(profile.account_state.value, "در حال بررسی")
            fa[screen] = (
                f"👤 حساب کاربری\n\n- نام نمایشی: {safe_text(profile.display_name)}\n"
                f"- وضعیت اتصال تلگرام: {'فعال' if profile.telegram_linked else 'غیرفعال'}\n"
                f"- وضعیت حساب: {safe_text(account_label)}\n"
                f"- تاریخ عضویت: {safe_date(profile.created_at)}"
                + (
                    f"\n- نام کاربری تلگرام: @{safe_text(profile.username)}"
                    if profile.username
                    else ""
                )
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
            recent = transactions or []
            lines = [
                f"• {'+' if tx.transaction_type.lower() in {'credit', 'topup'} else '−'}"
                f"{format_toman(abs(tx.amount_minor))} — {safe_date(tx.created_at)}"
                for tx in recent[:5]
            ]
            text = (
                f"💳 موجودی\n\n{format_toman(wallet_balance)}\n\nتراکنش‌های اخیر:\n"
                + ("\n".join(lines) if lines else "تراکنشی ثبت نشده است.")
            )
            rows = [
                [
                    {
                        "text": "➕ افزایش موجودی",
                        "callback_data": cb(CallbackAction.TOP_UP),
                    }
                ],
                [
                    {
                        "text": "📋 درخواست‌های کارت‌به‌کارت",
                        "callback_data": cb(CallbackAction.LIST_MANUAL_TOPUPS),
                    }
                ],
                *self.nav_rows(locale),
            ]
            return RenderedScreen(text, rows, screen)
        if screen == ScreenId.SETTINGS:
            rows = [
                [
                    {
                        "text": "🔒 حریم خصوصی",
                        "callback_data": cb(
                            CallbackAction.NAVIGATE, ScreenId.PRIVACY.value
                        ),
                    },
                    {
                        "text": "🔔 اعلان‌ها",
                        "callback_data": cb(
                            CallbackAction.NAVIGATE, ScreenId.NOTIFICATIONS.value
                        ),
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
            fa.get(screen, "⚠️ این بخش در حال آماده‌سازی است."),
            self.nav_rows(locale),
            screen,
        )
