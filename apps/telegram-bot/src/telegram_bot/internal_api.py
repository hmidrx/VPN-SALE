"""Strict, private platform adapter used by the production bot runtime."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from telegram_bot.application.identity import (
    AccountStatus,
    RegisterOrUpdateTelegramBotUser,
    TelegramIdentityPort,
    TelegramIdentityResult,
)
from telegram_bot.portal import (
    CustomerContext,
    CustomerPortalPort,
    CustomerProfile,
    ManualTopup,
    NotificationPreferences,
    ServiceSummary,
    WalletTransaction,
)


class PrivateApiUnavailable(RuntimeError):
    """Customer-safe boundary: response bodies and credentials never escape."""


class PrivatePlatformClient(TelegramIdentityPort, CustomerPortalPort):
    def __init__(self, base_url: str, token_file: str, *, timeout: float = 5.0) -> None:
        if not base_url.startswith("http://") and not base_url.startswith("https://"):
            raise ValueError("invalid internal API URL")
        token = Path(token_file).read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise ValueError("invalid internal API credential")
        self._base = base_url.rstrip("/") + "/api/v1/internal/telegram"
        self._token = token
        self._timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        telegram_id: int,
        body: object = None,
        idempotency_key: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Telegram-Subject": str(telegram_id),
            "Accept": "application/json",
        }
        data = None
        if isinstance(body, bytes):
            data = body
            headers["Content-Type"] = content_type or "application/octet-stream"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(  # noqa: S310 - validated internal base URL
            self._base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                return cast(dict[str, Any], json.loads(response.read(1_048_576).decode()))
        except (urllib.error.URLError, ValueError, OSError) as exc:
            raise PrivateApiUnavailable("سرویس موقتاً در دسترس نیست.") from exc

    def register_or_update(
        self, command: RegisterOrUpdateTelegramBotUser
    ) -> TelegramIdentityResult:
        data = self._request(
            "POST",
            "/identity/resolve",
            command.telegram_user_id,
            {
                "telegram_user_id": command.telegram_user_id,
                "username": command.username,
                "first_name": command.first_name,
                "last_name": command.last_name,
                "language_code": command.language_code,
                "bot_started": command.bot_started,
            },
        )
        return TelegramIdentityResult(
            str(data["customer_reference"]),
            AccountStatus(str(data["account_state"])),
            bool(data["created"]),
            cast(str | None, data.get("locale")),
        )

    def mark_bot_blocked(self, telegram_user_id: int) -> None:
        self._request("POST", "/identity/blocked", telegram_user_id, {})

    def profile(self, context: CustomerContext) -> CustomerProfile:
        data = self._request("GET", "/profile", context.telegram_user_id)
        return CustomerProfile(
            str(data["display_name"]),
            bool(data["telegram_linked"]),
            AccountStatus(str(data["account_state"])),
            datetime.fromisoformat(str(data["created_at"])),
            str(data.get("locale", "fa")),
            cast(str | None, data.get("username")),
        )

    def services(self, context: CustomerContext) -> list[ServiceSummary]:
        data = self._request("GET", "/services", context.telegram_user_id)
        return [
            ServiceSummary(
                str(x["reference"]),
                context.customer_ref,
                str(x["plan_name"]),
                str(x["status"]),
                datetime.fromisoformat(str(x["expires_at"])) if x.get("expires_at") else None,
                None,
                (int(x["traffic_entitlement_bytes"]) // (1024**3))
                if isinstance(x.get("traffic_entitlement_bytes"), int)
                else None,
                str(x["location"]) if x.get("location") else None,
                bool(x.get("renewable", False)),
            )
            for x in cast(list[dict[str, Any]], data["items"])
        ]

    def service(self, context: CustomerContext, service_ref: str) -> ServiceSummary | None:
        try:
            data = self._request("GET", f"/services/{service_ref}", context.telegram_user_id)
        except PrivateApiUnavailable:
            return None
        return ServiceSummary(
            str(data["reference"]),
            context.customer_ref,
            str(data["plan_name"]),
            str(data["status"]),
            datetime.fromisoformat(str(data["expires_at"])) if data.get("expires_at") else None,
            None,
            int(data["traffic_entitlement_bytes"]) // (1024**3)
            if isinstance(data.get("traffic_entitlement_bytes"), int)
            else None,
            str(data["location"]) if data.get("location") else None,
            bool(data.get("renewable", False)),
        )

    def wallet_balance(self, context: CustomerContext) -> tuple[int, str]:
        data = self._request("GET", "/wallet", context.telegram_user_id)
        return int(data["balance_minor"]), str(data["currency"])

    def transactions(self, context: CustomerContext) -> list[WalletTransaction]:
        data = self._request("GET", "/wallet/transactions", context.telegram_user_id)
        return [
            WalletTransaction(
                str(x["reference"]),
                int(x["amount_minor"]),
                str(x["currency"]),
                str(x["status"]),
                str(x["transaction_type"]),
                datetime.fromisoformat(str(x["created_at"])),
            )
            for x in cast(list[dict[str, Any]], data["items"])
        ]

    def notification_preferences(self, context: CustomerContext) -> NotificationPreferences:
        return NotificationPreferences(
            **self._request("GET", "/notification-preferences", context.telegram_user_id)
        )

    def update_notification_preference(
        self, context: CustomerContext, key: str, enabled: bool, idempotency_key: str
    ) -> NotificationPreferences:
        return NotificationPreferences(
            **self._request(
                "PATCH",
                f"/notification-preferences/{key}",
                context.telegram_user_id,
                {"enabled": enabled},
                idempotency_key,
            )
        )

    @staticmethod
    def _manual_topup(data: dict[str, Any]) -> ManualTopup:
        return ManualTopup(
            str(data["reference"]),
            int(data["amount_toman"]),
            str(data["status"]),
            datetime.fromisoformat(str(data["created_at"])),
            datetime.fromisoformat(str(data["submitted_at"])) if data.get("submitted_at") else None,
            int(data["verified_amount_toman"])
            if data.get("verified_amount_toman") is not None
            else None,
            int(data["bonus_amount_toman"]) if data.get("bonus_amount_toman") is not None else None,
            int(data["total_credited_toman"])
            if data.get("total_credited_toman") is not None
            else None,
        )

    def create_manual_topup(
        self, context: CustomerContext, amount_rial: int, idempotency_key: str
    ) -> ManualTopup:
        return self._manual_topup(
            self._request(
                "POST",
                "/manual-topups",
                context.telegram_user_id,
                {"amount_rial": amount_rial},
                idempotency_key,
            )
        )

    def manual_topups(self, context: CustomerContext) -> list[ManualTopup]:
        data = self._request("GET", "/manual-topups", context.telegram_user_id)
        return [self._manual_topup(item) for item in cast(list[dict[str, Any]], data["items"])]

    def manual_topup(self, context: CustomerContext, reference: str) -> ManualTopup | None:
        try:
            return self._manual_topup(
                self._request("GET", f"/manual-topups/{reference}", context.telegram_user_id)
            )
        except PrivateApiUnavailable:
            return None

    def manual_topup_destination_mode(self, context: CustomerContext, reference: str) -> str:
        data = self._request(
            "GET", f"/manual-topups/{reference}/destination-mode", context.telegram_user_id
        )
        return str(data["mode"])

    def upload_manual_topup_receipt(
        self,
        context: CustomerContext,
        reference: str,
        content: bytes,
        content_type: str,
        idempotency_key: str,
    ) -> ManualTopup:
        return self._manual_topup(
            self._request(
                "POST",
                f"/manual-topups/{reference}/receipt",
                context.telegram_user_id,
                content,
                idempotency_key,
                content_type,
            )
        )

    def sessions(self, context: CustomerContext) -> list[Any]:
        return []

    def revoke_session(self, context: CustomerContext, session_ref: str) -> bool:
        return False

    def create_ticket(
        self, context: CustomerContext, category: str, subject: str, message: str
    ) -> Any:
        raise PrivateApiUnavailable("پشتیبانی در مینی‌اپ در دسترس است.")

    def tickets(self, context: CustomerContext) -> list[Any]:
        return []
