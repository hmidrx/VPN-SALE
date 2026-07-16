from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VPN-SALE API"
    environment: str = "local"
    version: str = "0.0.0-milestone0"
    database_url: str = Field(
        default="postgresql+asyncpg://vpnsale:vpnsale_dev_password@localhost:5432/vpnsale"
    )
    redis_url: str = "redis://localhost:6379/0"
    metrics_enabled: bool = True
    password_argon2_time_cost: int = 3
    password_argon2_memory_cost: int = 65536
    password_argon2_parallelism: int = 4
    opaque_token_bytes: int = 32
    opaque_token_hash_salt: str = "vpnsale-identity-token-v1"  # noqa: S105
    identity_encryption_key: str = ""
    identity_encryption_key_version: str = "dev-v1"
    admin_access_token_signing_key: str = "dev-disposable-admin-access-token-signing-key-change-me"  # noqa: S105
    admin_access_token_key_id: str = "dev-v1"  # noqa: S105
    admin_access_token_issuer: str = "vpnsale-admin"  # noqa: S105
    admin_access_token_audience: str = "vpnsale-admin-api"  # noqa: S105
    admin_access_token_lifetime_seconds: int = 900
    admin_access_token_clock_skew_seconds: int = 30
    admin_session_idle_timeout_seconds: int = 1800
    admin_session_absolute_lifetime_seconds: int = 2592000
    admin_refresh_cookie_name: str = "vpnsale_admin_refresh"
    admin_refresh_cookie_path: str = "/api/v1/admin/auth"
    admin_refresh_cookie_domain: str = ""
    admin_refresh_cookie_secure: bool = True
    admin_refresh_cookie_samesite: str = "lax"
    admin_csrf_secret: str = "dev-disposable-csrf-secret-change-me"  # noqa: S105
    admin_lockout_threshold: int = 5
    admin_lockout_duration_seconds: int = 900
    admin_login_rate_limit: int = 10
    admin_login_rate_limit_window_seconds: int = 300
    admin_mfa_challenge_lifetime_seconds: int = 300
    admin_totp_enrollment_lifetime_seconds: int = 600
    admin_totp_issuer: str = "VPN-SALE Admin"
    admin_totp_clock_window: int = 1
    admin_recovery_code_count: int = 10
    admin_password_min_length: int = 14
    admin_password_max_length: int = 512

    telegram_bot_token: str = ""
    telegram_init_data_max_age_seconds: int = 86400
    telegram_init_data_future_skew_seconds: int = 60
    telegram_init_data_max_length: int = 4096
    telegram_customer_auth_enabled: bool = True
    fake_customer_auth_enabled: bool = False
    customer_access_token_signing_key: str = (
        "dev-disposable-customer-access-token-signing-key-change-me"  # noqa: S105
    )
    customer_access_token_key_id: str = "dev-v1"  # noqa: S105
    customer_access_token_issuer: str = "vpnsale-customer"  # noqa: S105
    customer_access_token_audience: str = "vpnsale-customer-api"  # noqa: S105
    customer_access_token_lifetime_seconds: int = 900
    customer_access_token_clock_skew_seconds: int = 30
    customer_session_idle_timeout_seconds: int = 2592000
    customer_session_absolute_lifetime_seconds: int = 7776000
    customer_refresh_cookie_name: str = "vpnsale_customer_refresh"
    customer_refresh_cookie_path: str = "/api/v1/customer/auth"
    customer_refresh_cookie_domain: str = ""
    customer_refresh_cookie_secure: bool = True
    customer_refresh_cookie_samesite: str = "lax"
    customer_csrf_secret: str = "dev-disposable-customer-csrf-secret-change-me"  # noqa: S105
    customer_login_rate_limit: int = 20
    customer_login_rate_limit_window_seconds: int = 300
    customer_refresh_rate_limit: int = 60
    customer_refresh_rate_limit_window_seconds: int = 300
    customer_session_revocation_rate_limit: int = 30
    customer_session_revocation_rate_limit_window_seconds: int = 300
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VPN_SALE_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_security_configuration(settings: Settings) -> None:
    production_like = settings.environment.lower() in {"production", "prod", "staging"}
    if production_like:
        if not settings.identity_encryption_key:
            raise ValueError("identity encryption key is required")
        if (
            not settings.admin_access_token_signing_key
            or "change-me" in settings.admin_access_token_signing_key
        ):
            raise ValueError("admin access-token signing key is required")
        if not settings.admin_csrf_secret or "change-me" in settings.admin_csrf_secret:
            raise ValueError("admin CSRF secret is required")
        if not settings.admin_refresh_cookie_secure:
            raise ValueError("admin refresh cookie must be Secure in production")
        if settings.telegram_customer_auth_enabled and not settings.telegram_bot_token:
            raise ValueError(
                "Telegram bot token is required when customer Telegram auth is enabled"
            )
        if (
            not settings.customer_access_token_signing_key
            or "change-me" in settings.customer_access_token_signing_key
        ):
            raise ValueError("customer access-token signing key is required")
        if not settings.customer_csrf_secret or "change-me" in settings.customer_csrf_secret:
            raise ValueError("customer CSRF secret is required")
        if not settings.customer_refresh_cookie_secure:
            raise ValueError("customer refresh cookie must be Secure in production")
        if settings.fake_customer_auth_enabled:
            raise ValueError("fake customer authentication is forbidden in production")
