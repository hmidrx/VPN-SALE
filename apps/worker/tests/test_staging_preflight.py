from __future__ import annotations

import pytest

from platform_worker.staging_preflight import (
    StagingPreflightError,
    StagingProviderReadiness,
    validate_staging_environment,
)


def _environment() -> dict[str, str]:
    return {
        "VPN_SALE_ENVIRONMENT": "staging",
        "VPN_SALE_PROVIDER_WRITES_ENABLED": "true",
        "VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED": "false",
        "VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED": "false",
        "VPN_SALE_BOT_ENABLED": "true",
        "VPN_SALE_BOT_MODE": "polling",
        "VPN_SALE_TELEGRAM_BOT_TOKEN": "x",
        "PROVIDER_VAULT_MASTER_KEY_B64": "x",
    }


def test_staging_environment_requires_explicit_safe_provider_write_context() -> None:
    validate_staging_environment(_environment())

    unsafe_cases = (
        ("VPN_SALE_ENVIRONMENT", "production"),
        ("VPN_SALE_ENVIRONMENT", "test"),
        ("VPN_SALE_PROVIDER_WRITES_ENABLED", "false"),
        ("VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED", "true"),
        ("VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED", "true"),
        ("VPN_SALE_BOT_ENABLED", "false"),
        ("VPN_SALE_BOT_MODE", "webhook"),
        ("VPN_SALE_TELEGRAM_BOT_TOKEN", ""),
        ("PROVIDER_VAULT_MASTER_KEY_B64", ""),
    )
    for key, value in unsafe_cases:
        candidate = _environment()
        candidate[key] = value
        with pytest.raises(StagingPreflightError):
            validate_staging_environment(candidate)


def test_staging_readiness_requires_every_authoritative_configuration_layer() -> None:
    assert StagingProviderReadiness(1, 1, 1, 1).ready is True
    for values in (
        (0, 1, 1, 1),
        (1, 0, 1, 1),
        (1, 1, 0, 1),
        (1, 1, 1, 0),
    ):
        assert StagingProviderReadiness(*values).ready is False
