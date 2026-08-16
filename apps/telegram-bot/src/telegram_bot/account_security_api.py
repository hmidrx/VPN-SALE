"""Production Telegram account-security adapter over the private platform bridge."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, cast

from telegram_bot.delivery_api import DeliveryPrivatePlatformClient
from telegram_bot.internal_api import PrivateApiUnavailable
from telegram_bot.portal import CustomerContext, SessionSummary

_SESSION_REFERENCE = re.compile(r"^ses_[0-9a-f]{24}$")


class AccountSecurityPrivatePlatformClient(DeliveryPrivatePlatformClient):
    """Expose only opaque web-session projections to the Telegram bot."""

    @staticmethod
    def _session(data: dict[str, Any]) -> SessionSummary:
        reference = data.get("reference")
        label = data.get("label")
        last_seen = data.get("last_seen_at")
        if (
            not isinstance(reference, str)
            or _SESSION_REFERENCE.fullmatch(reference) is None
            or not isinstance(label, str)
            or not label.strip()
            or len(label) > 80
            or not isinstance(last_seen, str)
        ):
            raise PrivateApiUnavailable("اطلاعات نشست‌های حساب قابل استفاده نیست.")
        try:
            parsed_last_seen = datetime.fromisoformat(last_seen)
        except ValueError as exc:
            raise PrivateApiUnavailable("اطلاعات نشست‌های حساب قابل استفاده نیست.") from exc
        return SessionSummary(
            reference,
            label.strip(),
            parsed_last_seen,
            data.get("current") is True,
        )

    def sessions(self, context: CustomerContext) -> list[SessionSummary]:
        data = self._request("GET", "/sessions", context.telegram_user_id)
        raw_items = data.get("items")
        if not isinstance(raw_items, list) or len(raw_items) > 100:
            raise PrivateApiUnavailable("اطلاعات نشست‌های حساب قابل استفاده نیست.")
        return [self._session(item) for item in cast(list[dict[str, Any]], raw_items)]

    def revoke_session(self, context: CustomerContext, session_ref: str) -> bool:
        if _SESSION_REFERENCE.fullmatch(session_ref) is None:
            return False
        data = self._request(
            "POST",
            f"/sessions/{session_ref}/revoke",
            context.telegram_user_id,
            {},
        )
        return data.get("status") == "REVOKED"
