"""Explicit Telegram delivery UX layered on truthful purchase rendering."""

from __future__ import annotations

from typing import Any, Protocol, cast

from telegram_bot.application.identity import TelegramIdentityPort
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.delivery_api import SubscriptionDelivery
from telegram_bot.internal_api import AuthoritativePrivateApiError, PrivateApiUnavailable
from telegram_bot.portal import CustomerContext, CustomerPortalPort
from telegram_bot.runtime.handlers import HandlerResult, IncomingUser
from telegram_bot.runtime.purchase_truth import (
    TruthfulPurchaseBotCommandHandler,
    TruthfulTelegramPollingRuntime,
)
from telegram_bot.screens import safe_text
from telegram_bot.transport.polling import TelegramTransport, UrlLibTelegramTransport


class DeliveryPortal(Protocol):
    def service_delivery_ready(self, context: CustomerContext, service_reference: str) -> bool: ...

    def issue_subscription(
        self, context: CustomerContext, service_reference: str
    ) -> SubscriptionDelivery: ...

    def rotate_subscription(
        self, context: CustomerContext, service_reference: str
    ) -> SubscriptionDelivery: ...

    def revoke_subscription(self, context: CustomerContext, service_reference: str) -> str: ...

    def connection_uri(self, context: CustomerContext, service_reference: str) -> str: ...


def privacy_safe_telegram_payload(method: str, payload: dict[str, object]) -> dict[str, object]:
    """Disable Telegram link previews for messages that can contain delivery secrets."""
    safe_payload = dict(payload)
    if method in {"sendMessage", "editMessageText"}:
        safe_payload.setdefault("link_preview_options", {"is_disabled": True})
    return safe_payload


class PrivacyAwareTelegramTransport(UrlLibTelegramTransport):
    async def call(
        self, method: str, payload: dict[str, object] | None = None
    ) -> dict[str, Any]:
        return await super().call(method, privacy_safe_telegram_payload(method, payload or {}))


class SecureDeliveryBotCommandHandler(TruthfulPurchaseBotCommandHandler):
    """Reveal delivery material only after explicit, rate-limited customer actions."""

    def _delivery_portal(self) -> DeliveryPortal:
        return cast(DeliveryPortal, self.portal)

    def _service_rows(
        self, service_reference: str, locale: str, ready: bool
    ) -> list[list[dict[str, str]]]:
        rows: list[list[dict[str, str]]] = []
        if ready:
            rows.append(
                [
                    {
                        "text": "🔐 لینک اشتراک",
                        "callback_data": BotCallback(
                            CallbackAction.OPEN_SUBSCRIPTION, service_reference
                        ).pack(),
                    },
                    {
                        "text": "📋 کانفیگ مستقیم",
                        "callback_data": BotCallback(
                            CallbackAction.OPEN_CONFIGS, service_reference
                        ).pack(),
                    },
                ]
            )
        rows.extend(self.renderer.nav_rows(locale))
        return rows

    def _subscription_rows(
        self, service_reference: str, locale: str
    ) -> list[list[dict[str, str]]]:
        return [
            [
                {
                    "text": "🔄 ساخت لینک جدید",
                    "callback_data": BotCallback(
                        CallbackAction.ROTATE_SUBSCRIPTION, service_reference
                    ).pack(),
                },
                {
                    "text": "🗑 لغو اشتراک",
                    "callback_data": BotCallback(
                        CallbackAction.REVOKE_SUBSCRIPTION, service_reference
                    ).pack(),
                },
            ],
            [
                {
                    "text": "📋 کانفیگ مستقیم",
                    "callback_data": BotCallback(
                        CallbackAction.OPEN_CONFIGS, service_reference
                    ).pack(),
                }
            ],
            *self.renderer.nav_rows(locale),
        ]

    @staticmethod
    def _subscription_text(delivery: SubscriptionDelivery, *, rotated: bool = False) -> str:
        if not delivery.newly_issued:
            return (
                "🔐 برای این سرویس قبلاً لینک اشتراک صادر شده است.\n\n"
                "به‌دلیل سیاست امنیتی، لینک قبلی از روی سرور قابل بازسازی یا نمایش دوباره نیست. "
                "اگر لینک را ندارید، «ساخت لینک جدید» را بزنید."
            )
        labels = {
            "base64": "لینک اصلی",
            "links": "لینک‌های خام",
            "mihomo": "Mihomo",
            "clash": "Clash قدیمی (در صورت سازگاری)",
            "sing_box": "sing-box",
        }
        lines = [
            "🔄 لینک اشتراک جدید ساخته شد." if rotated else "🔐 لینک اشتراک شما آماده است.",
            "",
        ]
        for key in ("base64", "mihomo", "sing_box", "links", "clash"):
            value = delivery.urls.get(key)
            if value:
                lines.extend([f"{labels[key]}:", value, ""])
        if rotated:
            lines.append("لینک قبلی حداکثر تا ۵ دقیقه برای دوره انتقال معتبر می‌ماند.")
        lines.append("⚠️ این لینک‌ها محرمانه‌اند؛ آن‌ها را برای شخص دیگری ارسال نکنید.")
        return "\n".join(lines)

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        context = self._portal_context(user, locale)
        delivery_portal = self._delivery_portal()

        if callback.action == CallbackAction.OPEN_SERVICE:
            if not callback.value:
                return self._stale(locale)
            service = self.portal.service(context, callback.value)
            if service is None:
                return self._callback_message(
                    "این سرویس پیدا نشد یا متعلق به شما نیست.", self.renderer.nav_rows(locale)
                )
            ready = False
            try:
                ready = delivery_portal.service_delivery_ready(context, callback.value)
            except PrivateApiUnavailable:
                ready = False
            status_label = {
                "active": "فعال",
                "pending": "در حال آماده‌سازی",
                "expired": "پایان‌یافته",
                "failed": "ناموفق",
                "suspended": "محدود",
            }.get(service.status.casefold(), "در حال بررسی")
            text = f"{safe_text(service.plan_name)}\nوضعیت: {status_label}"
            if service.status.casefold() == "active" and not ready:
                text += "\n\nتحویل کانفیگ در حال حاضر قابل تأیید نیست؛ کمی بعد دوباره بررسی کنید."
            return self._callback_message(
                text, self._service_rows(callback.value, locale, ready)
            )

        if callback.action == CallbackAction.OPEN_SUBSCRIPTION:
            if not callback.value:
                return self._stale(locale)
            try:
                delivery = delivery_portal.issue_subscription(context, callback.value)
            except AuthoritativePrivateApiError:
                return self._callback_message(
                    "اشتراک این سرویس در وضعیت فعلی قابل تحویل نیست.",
                    self.renderer.nav_rows(locale),
                )
            except PrivateApiUnavailable:
                return self._callback_message(
                    "نتیجه صدور لینک مشخص نشد و برای جلوگیری از جابه‌جایی ناخواسته رمز، "
                    "درخواست خودکار تکرار نشد.\n\n"
                    "اگر لینکی دریافت نکردید، می‌توانید از «ساخت لینک جدید» برای بازیابی "
                    "دسترسی استفاده کنید.",
                    self._subscription_rows(callback.value, locale),
                )
            return self._callback_message(
                self._subscription_text(delivery),
                self._subscription_rows(callback.value, locale),
            )

        if callback.action == CallbackAction.ROTATE_SUBSCRIPTION:
            if not callback.value:
                return self._stale(locale)
            try:
                delivery = delivery_portal.rotate_subscription(context, callback.value)
            except AuthoritativePrivateApiError:
                return self._callback_message(
                    "ساخت لینک جدید فعلاً ممکن نیست. اگر همین چند لحظه قبل لینک را عوض کرده‌اید، "
                    "پس از پایان دوره انتقال دوباره تلاش کنید.",
                    self._subscription_rows(callback.value, locale),
                )
            except PrivateApiUnavailable:
                return self._callback_message(
                    "نتیجه تغییر لینک مشخص نشد. درخواست خودکار تکرار نشد تا وضعیت رمز اشتراک "
                    "مبهم‌تر نشود.\nچند دقیقه بعد وضعیت اشتراک را دوباره باز کنید.",
                    self.renderer.nav_rows(locale),
                )
            return self._callback_message(
                self._subscription_text(delivery, rotated=True),
                self._subscription_rows(callback.value, locale),
            )

        if callback.action == CallbackAction.REVOKE_SUBSCRIPTION:
            if not callback.value:
                return self._stale(locale)
            return self._callback_message(
                "با لغو اشتراک، لینک فعلی و لینک‌های دوره انتقال از دسترس خارج می‌شوند.\n\n"
                "آیا مطمئن هستید؟",
                [
                    [
                        {
                            "text": "✅ بله، لغو شود",
                            "callback_data": BotCallback(
                                CallbackAction.CONFIRM_REVOKE_SUBSCRIPTION, callback.value
                            ).pack(),
                        },
                        {
                            "text": "◀️ انصراف",
                            "callback_data": BotCallback(
                                CallbackAction.OPEN_SERVICE, callback.value
                            ).pack(),
                        },
                    ]
                ],
            )

        if callback.action == CallbackAction.CONFIRM_REVOKE_SUBSCRIPTION:
            if not callback.value:
                return self._stale(locale)
            try:
                status_value = delivery_portal.revoke_subscription(context, callback.value)
            except AuthoritativePrivateApiError:
                return self._callback_message(
                    "اشتراک فعالی برای لغو پیدا نشد.", self.renderer.nav_rows(locale)
                )
            except PrivateApiUnavailable:
                return self._callback_message(
                    "نتیجه لغو مشخص نشد. این عملیات قابل تکرار است؛ دوباره تأیید کنید یا "
                    "بعداً وضعیت را بررسی کنید.",
                    [
                        [
                            {
                                "text": "🔁 تأیید دوباره لغو",
                                "callback_data": BotCallback(
                                    CallbackAction.CONFIRM_REVOKE_SUBSCRIPTION, callback.value
                                ).pack(),
                            }
                        ],
                        *self.renderer.nav_rows(locale),
                    ],
                )
            if status_value != "REVOKED":
                return self._callback_message(
                    "وضعیت اشتراک قابل تأیید نیست؛ بعداً دوباره بررسی کنید.",
                    self.renderer.nav_rows(locale),
                )
            return self._callback_message(
                "✅ لینک اشتراک لغو شد و دیگر قابل استفاده نیست.",
                [
                    [
                        {
                            "text": "🔐 ساخت اشتراک جدید",
                            "callback_data": BotCallback(
                                CallbackAction.OPEN_SUBSCRIPTION, callback.value
                            ).pack(),
                        }
                    ],
                    *self.renderer.nav_rows(locale),
                ],
            )

        if callback.action == CallbackAction.OPEN_CONFIGS:
            if not callback.value:
                return self._stale(locale)
            # OPEN_CONFIGS is legacy-classified as navigation in the base handler. Enforce the
            # stronger sensitive policy here before revealing any credential material.
            if not self._allow_callback(user.telegram_user_id, "sensitive"):
                return self._limited_callback(user.telegram_user_id, "sensitive")
            try:
                connection_uri = delivery_portal.connection_uri(context, callback.value)
            except (AuthoritativePrivateApiError, PrivateApiUnavailable):
                return self._callback_message(
                    "کانفیگ این سرویس در حال حاضر قابل تحویل نیست.", self.renderer.nav_rows(locale)
                )
            return self._callback_message(
                "📋 کانفیگ مستقیم سرویس\n\n"
                f"{connection_uri}\n\n"
                "⚠️ این کانفیگ محرمانه است و فقط برای استفاده شخصی شما نمایش داده شده است.",
                [
                    [
                        {
                            "text": "🔐 لینک اشتراک",
                            "callback_data": BotCallback(
                                CallbackAction.OPEN_SUBSCRIPTION, callback.value
                            ).pack(),
                        }
                    ],
                    *self.renderer.nav_rows(locale),
                ],
            )

        return super()._route_callback(user, locale, callback, update_id)


class SecureDeliveryTelegramPollingRuntime(TruthfulTelegramPollingRuntime):
    """Production polling runtime with truthful purchase and explicit secure delivery UX."""

    def __init__(
        self,
        settings: BotSettings,
        identity: TelegramIdentityPort,
        transport: TelegramTransport | None = None,
        *,
        portal: CustomerPortalPort | None = None,
        conversations: ConversationStoreV2 | None = None,
        retry_base_seconds: float = 0.2,
        retry_max_seconds: float = 5.0,
    ) -> None:
        super().__init__(
            settings,
            identity,
            transport,
            portal=portal,
            conversations=conversations,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )
        self.handler = SecureDeliveryBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )
