from __future__ import annotations

import os

from platform_api.config import Settings
from platform_api.operations import (
    CertificationResult,
    build_provider_certification_summary,
    build_readiness_report,
    release_metadata,
    sanitize_mapping,
    validate_environment_profile,
)


def test_production_configuration_fails_closed_without_secrets() -> None:
    settings = Settings(environment="PRODUCTION", telegram_customer_auth_enabled=False)
    issues = validate_environment_profile(settings)
    variables = {issue.variable for issue in issues if issue.severity == "error"}
    assert "VPN_SALE_IDENTITY_ENCRYPTION_KEY" in variables
    assert "VPN_SALE_PUBLIC_APP_ORIGIN" in variables


def test_staging_rejects_wildcard_credentialed_cors() -> None:
    values = {
        "environment": "STAGING",
        "identity_encryption_key": "test-key",
        "admin_access_token_signing_key": "safe-admin-signing-key",
        "admin_csrf_secret": "safe-admin-csrf",
        "customer_access_token_signing_key": "safe-customer-signing-key",
        "customer_csrf_secret": "safe-customer-csrf",
        "telegram_customer_auth_enabled": False,
        "public_app_origin": "https://staging.example.test",
        "api_public_origin": "https://api.staging.example.test",
        "subscription_public_origin": "https://sub.staging.example.test",
        "cors_allowed_origins": ["*"],
        "cors_allow_credentials": True,
    }
    settings = Settings.model_validate(values)
    assert any(
        issue.variable == "VPN_SALE_CORS_ALLOWED_ORIGINS"
        for issue in validate_environment_profile(settings)
    )


def test_release_metadata_is_sanitized() -> None:
    os.environ["VPN_SALE_COMMIT_SHA"] = "a" * 80
    metadata = release_metadata(Settings())
    assert metadata["commit_sha"] == "a" * 40
    assert "password" not in " ".join(metadata.values()).lower()


def test_live_provider_certification_defaults_to_not_run() -> None:
    os.environ.pop("VPN_SALE_PROVIDER_LIVE_ACK", None)
    summaries = build_provider_certification_summary()
    assert {item.provider for item in summaries} == {"sanaei-3x-ui", "alireza-x-ui", "pasarguard"}
    assert all(item.result == CertificationResult.NOT_RUN for item in summaries)
    assert all(not item.live_read_enabled for item in summaries)


def test_readiness_report_never_declares_production_ready() -> None:
    report = build_readiness_report(Settings(environment="PRODUCTION"), {"configuration": "PASS"})
    assert report.release_state.value != "PRODUCTION_READY"
    assert (
        "live provider certification requires dedicated staging panels" in report.release_blockers
    )


def test_sanitizer_redacts_secret_named_fields() -> None:
    sanitized = sanitize_mapping({"api_token": "secret-value", "status": "ok"})
    assert sanitized == {"api_token": "<redacted>", "status": "ok"}
