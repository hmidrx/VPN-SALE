"""Sensitive delivery operations over the existing private Telegram platform bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

from telegram_bot.internal_api import PrivateApiUnavailable, PrivatePlatformClient
from telegram_bot.portal import CustomerContext

_ALLOWED_URL_KEYS = frozenset({"base64", "links", "mihomo", "clash", "sing_box"})
_ALLOWED_CONNECTION_SCHEMES = frozenset({"vless", "vmess", "trojan", "ss"})


@dataclass(frozen=True)
class SubscriptionDelivery:
    status: str
    newly_issued: bool
    urls: dict[str, str]


class DeliveryPrivatePlatformClient(PrivatePlatformClient):
    """Adds transient secret delivery without persisting returned credentials in bot state."""

    @staticmethod
    def _subscription_delivery(data: dict[str, Any]) -> SubscriptionDelivery:
        raw_urls = data.get("urls", {})
        if not isinstance(raw_urls, dict):
            raise PrivateApiUnavailable("اطلاعات اشتراک قابل استفاده نیست.")
        urls: dict[str, str] = {}
        for key, value in cast(dict[object, object], raw_urls).items():
            if (
                not isinstance(key, str)
                or key not in _ALLOWED_URL_KEYS
                or not isinstance(value, str)
            ):
                raise PrivateApiUnavailable("اطلاعات اشتراک قابل استفاده نیست.")
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or len(value) > 4096
            ):
                raise PrivateApiUnavailable("اطلاعات اشتراک قابل استفاده نیست.")
            urls[key] = value
        newly_issued = data.get("newly_issued") is True
        if newly_issued and "base64" not in urls:
            raise PrivateApiUnavailable("اطلاعات اشتراک قابل استفاده نیست.")
        if not newly_issued and urls:
            raise PrivateApiUnavailable("اطلاعات اشتراک قابل استفاده نیست.")
        return SubscriptionDelivery(str(data.get("status") or "UNKNOWN"), newly_issued, urls)

    def service_delivery_ready(self, context: CustomerContext, service_reference: str) -> bool:
        data = self._request("GET", f"/services/{service_reference}", context.telegram_user_id)
        return (
            str(data.get("status") or "").upper() == "ACTIVE" and data.get("delivery_ready") is True
        )

    def issue_subscription(
        self, context: CustomerContext, service_reference: str
    ) -> SubscriptionDelivery:
        return self._subscription_delivery(
            self._request(
                "POST",
                f"/services/{service_reference}/subscription/issue",
                context.telegram_user_id,
                {},
            )
        )

    def rotate_subscription(
        self, context: CustomerContext, service_reference: str
    ) -> SubscriptionDelivery:
        return self._subscription_delivery(
            self._request(
                "POST",
                f"/services/{service_reference}/subscription/rotate",
                context.telegram_user_id,
                {},
            )
        )

    def revoke_subscription(self, context: CustomerContext, service_reference: str) -> str:
        data = self._request(
            "POST",
            f"/services/{service_reference}/subscription/revoke",
            context.telegram_user_id,
            {},
        )
        return str(data.get("status") or "UNKNOWN")

    def connection_uri(self, context: CustomerContext, service_reference: str) -> str:
        data = self._request(
            "GET",
            f"/services/{service_reference}/connection",
            context.telegram_user_id,
        )
        value = data.get("connection_uri")
        if not isinstance(value, str) or len(value) > 8192 or any(ch.isspace() for ch in value):
            raise PrivateApiUnavailable("کانفیگ قابل استفاده نیست.")
        if urlsplit(value).scheme.casefold() not in _ALLOWED_CONNECTION_SCHEMES:
            raise PrivateApiUnavailable("کانفیگ قابل استفاده نیست.")
        return value
