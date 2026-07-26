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
    public_account_registration_enabled: bool = False
    password_account_login_enabled: bool = False
    account_email_verification_enabled: bool = False
    account_recovery_enabled: bool = False
    telegram_account_linking_enabled: bool = False
    unified_admin_identity_enabled: bool = False
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
    customer_registration_rate_limit: int = 5
    customer_registration_global_rate_limit: int = 100
    customer_password_login_rate_limit: int = 10
    customer_password_min_length: int = Field(default=12, ge=12, le=512)
    customer_password_max_length: int = Field(default=512, ge=12, le=4096)
    customer_password_lockout_threshold: int = Field(default=5, ge=1, le=100)
    customer_password_lockout_duration_seconds: int = Field(default=900, ge=60, le=86400)
    customer_refresh_rate_limit: int = 60
    customer_refresh_rate_limit_window_seconds: int = 300
    customer_session_revocation_rate_limit: int = 30
    customer_session_revocation_rate_limit_window_seconds: int = 300

    catalog_quote_lifetime_seconds: int = Field(default=900, ge=60, le=86400)
    catalog_quote_idempotency_lifetime_seconds: int = Field(default=86400, ge=300, le=604800)
    catalog_quote_idempotency_key_max_length: int = Field(default=120, ge=16, le=240)
    catalog_default_currency: str = "IRR"
    catalog_money_unit: str = "rial"
    catalog_default_locale: str = "fa"
    catalog_max_page_size: int = Field(default=100, ge=1, le=250)
    catalog_max_custom_traffic_bytes: int = Field(default=10995116277760, gt=0)
    catalog_max_custom_duration_days: int = Field(default=3650, gt=0)
    catalog_max_device_count: int = Field(default=10000, gt=0)
    catalog_max_pricing_components: int = Field(default=64, ge=1, le=256)
    catalog_max_pricing_tiers: int = Field(default=128, ge=1, le=512)

    public_app_origin: str = "http://localhost:3000"
    api_public_origin: str = "http://localhost:8000"
    subscription_public_origin: str = "http://localhost:8000"
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    cors_allow_credentials: bool = True
    trusted_proxy_cidrs: list[str] = Field(default_factory=list)
    observability_otlp_endpoint: str = ""
    backup_destination_url: str = "file:///tmp/vpnsale-backups"
    backup_retention_days: int = Field(default=30, ge=1, le=3650)
    worker_concurrency: int = Field(default=4, ge=1, le=128)
    request_body_limit_bytes: int = Field(default=10485760, ge=1024, le=104857600)
    upload_file_limit_bytes: int = Field(default=5242880, ge=1024, le=52428800)
    maintenance_mode_enabled: bool = False
    provider_credential_vault_key_version: str = "dev-v1"
    object_storage_url: str = "file:///tmp/vpnsale-media"
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VPN_SALE_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_security_configuration(settings: Settings) -> None:
    incomplete_features = (
        settings.account_email_verification_enabled,
        settings.account_recovery_enabled,
        settings.telegram_account_linking_enabled,
        settings.unified_admin_identity_enabled,
    )
    if any(incomplete_features):
        raise ValueError("requested unified account feature is not implemented")
    if settings.customer_password_min_length > settings.customer_password_max_length:
        raise ValueError("customer password length settings are invalid")
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
