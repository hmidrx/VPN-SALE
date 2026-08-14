from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class BotMode(StrEnum):
    DISABLED = "disabled"
    POLLING = "polling"
    WEBHOOK = "webhook"


@dataclass(frozen=True)
class BotSettings:
    enabled: bool = False
    token: str = ""
    username: str = ""
    display_name: str = "VPN-SALE"
    mode: BotMode = BotMode.DISABLED
    environment: str = "local"
    webhook_base_url: str = ""
    webhook_path: str = "/telegram/webhook"
    webhook_secret_token: str = ""
    webhook_max_connections: int = 40
    webhook_request_size_limit: int = 256 * 1024
    allowed_updates: tuple[str, ...] = ("message", "callback_query")
    polling_timeout_seconds: int = 30
    mini_app_base_url: str = "http://localhost:3000"
    mini_app_allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    default_locale: str = "fa"
    supported_locales: tuple[str, ...] = ("fa",)
    update_idempotency_ttl_seconds: int = 86400
    command_rate_limit: int = 12
    command_rate_limit_window_seconds: int = 60
    navigation_rate_limit: int = 30
    navigation_rate_limit_window_seconds: int = 10
    mutation_rate_limit: int = 1
    mutation_rate_limit_window_seconds: int = 3
    sensitive_rate_limit: int = 12
    sensitive_rate_limit_window_seconds: int = 60
    throttle_notice_cooldown_seconds: int = 3
    rate_limit_secret: str = "dev-bot-rate-limit-secret-change-me"  # noqa: S105
    help_url: str = ""
    privacy_url: str = ""
    allow_polling_in_production: bool = False
    internal_api_url: str = ""
    internal_token_file: str = ""
    redis_url: str = ""

    @property
    def production_like(self) -> bool:
        return self.environment.lower() in {"production", "prod", "staging"}

    @property
    def webhook_url(self) -> str:
        return self.webhook_base_url.rstrip("/") + self.webhook_path

    def validate(self) -> None:
        if not self.enabled or self.mode == BotMode.DISABLED:
            return
        if not self.token:
            raise ValueError(
                "VPN_SALE_TELEGRAM_BOT_TOKEN is required when VPN_SALE_BOT_ENABLED=true"
            )
        if self.production_like and (not self.internal_api_url or not self.internal_token_file):
            raise ValueError("the private Telegram platform bridge is required")
        if self.production_like and not self.redis_url:
            raise ValueError("Redis is required for durable Telegram state")
        if (
            self.mode == BotMode.POLLING
            and self.production_like
            and not self.allow_polling_in_production
        ):
            raise ValueError(
                "VPN_SALE_BOT_MODE=polling is rejected in production-like environments"
            )
        if self.mode == BotMode.WEBHOOK:
            if not self.webhook_base_url or not self.webhook_secret_token:
                raise ValueError(
                    "VPN_SALE_TELEGRAM_WEBHOOK_BASE_URL and "
                    "VPN_SALE_TELEGRAM_WEBHOOK_SECRET_TOKEN are required"
                )
            _require_https_public(self.webhook_url, "webhook URL", self.production_like)
        _validate_mini_app(
            self.mini_app_base_url, self.mini_app_allowed_hosts, self.production_like
        )
        if self.default_locale not in self.supported_locales:
            raise ValueError(
                "VPN_SALE_TELEGRAM_DEFAULT_LOCALE must be listed in "
                "VPN_SALE_TELEGRAM_SUPPORTED_LOCALES"
            )


def _require_https_public(url: str, label: str, production_like: bool) -> None:
    parsed = urlparse(url)
    if production_like and parsed.scheme != "https":
        raise ValueError(f"{label} must use HTTPS in production")
    if production_like and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(f"{label} must not use localhost in production")


def _validate_mini_app(url: str, hosts: tuple[str, ...], production_like: bool) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in hosts:
        raise ValueError(
            "VPN_SALE_CUSTOMER_MINI_APP_URL host must be listed in "
            "VPN_SALE_CUSTOMER_MINI_APP_ALLOWED_HOSTS"
        )
    _require_https_public(url, "Mini App URL", production_like)
