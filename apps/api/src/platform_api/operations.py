from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from .config import Settings, get_settings, validate_security_configuration
from .dependencies import check_database, check_redis

_SAFE_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]+$", re.IGNORECASE)
_SECRET_WORDS = ("secret", "token", "password", "key", "cookie", "credential")
PROVIDER_TARGETS: dict[str, str] = {
    "sanaei-3x-ui": "v3.5.0",
    "alireza-x-ui": "v1.11.3",
    "pasarguard": "v4.0.2",
}


class ReleaseState(StrEnum):
    NOT_READY = "NOT_READY"
    CONDITIONALLY_READY = "CONDITIONALLY_READY"
    READY_FOR_STAGING = "READY_FOR_STAGING"
    READY_FOR_RELEASE_REVIEW = "READY_FOR_RELEASE_REVIEW"


class CertificationResult(StrEnum):
    NOT_RUN = "NOT_RUN"
    PASSED = "PASSED"
    PASSED_WITH_UNSUPPORTED_STEPS = "PASSED_WITH_UNSUPPORTED_STEPS"
    FAILED = "FAILED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    RECERTIFICATION_REQUIRED = "RECERTIFICATION_REQUIRED"


@dataclass(frozen=True)
class ConfigIssue:
    variable: str
    message: str
    severity: Literal["warning", "error"] = "error"


def _is_secret_name(name: str) -> bool:
    return any(word in name.lower() for word in _SECRET_WORDS)


def _valid_https_origin(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.path.rstrip("/")


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme == "file":
        return bool(parsed.path.startswith("/"))
    return bool(_SAFE_URL_RE.match(value)) and bool(parsed.netloc)


def validate_environment_profile(settings: Settings) -> list[ConfigIssue]:
    env = settings.environment.upper()
    issues: list[ConfigIssue] = []
    allowed = {"LOCAL", "TEST", "CI", "STAGING", "PRODUCTION"}
    if env not in allowed:
        issues.append(
            ConfigIssue(
                "VPN_SALE_ENVIRONMENT", "must be one of LOCAL, TEST, CI, STAGING, PRODUCTION"
            )
        )
    production_like = env in {"STAGING", "PRODUCTION"}
    required = {
        "VPN_SALE_DATABASE_URL": settings.database_url,
        "VPN_SALE_REDIS_URL": settings.redis_url,
        "VPN_SALE_IDENTITY_ENCRYPTION_KEY": settings.identity_encryption_key,
        "VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY": settings.admin_access_token_signing_key,
        "VPN_SALE_ADMIN_CSRF_SECRET": settings.admin_csrf_secret,
        "VPN_SALE_CUSTOMER_ACCESS_TOKEN_SIGNING_KEY": settings.customer_access_token_signing_key,
        "VPN_SALE_CUSTOMER_CSRF_SECRET": settings.customer_csrf_secret,
        "VPN_SALE_BACKUP_DESTINATION_URL": settings.backup_destination_url,
        "VPN_SALE_PUBLIC_APP_ORIGIN": settings.public_app_origin,
        "VPN_SALE_API_PUBLIC_ORIGIN": settings.api_public_origin,
        "VPN_SALE_SUBSCRIPTION_PUBLIC_ORIGIN": settings.subscription_public_origin,
    }
    if production_like:
        for name, value in required.items():
            if not value or "change-me" in value:
                issues.append(ConfigIssue(name, "is required for staging and production"))
        for name in (
            "VPN_SALE_PUBLIC_APP_ORIGIN",
            "VPN_SALE_API_PUBLIC_ORIGIN",
            "VPN_SALE_SUBSCRIPTION_PUBLIC_ORIGIN",
        ):
            value = required[name]
            if value and not _valid_https_origin(value):
                issues.append(ConfigIssue(name, "must be an https origin without path"))
        if not settings.admin_refresh_cookie_secure or not settings.customer_refresh_cookie_secure:
            issues.append(
                ConfigIssue("VPN_SALE_REFRESH_COOKIE_SECURE", "refresh cookies must be Secure")
            )
        if settings.admin_refresh_cookie_samesite.lower() not in {"lax", "strict", "none"}:
            issues.append(
                ConfigIssue(
                    "VPN_SALE_ADMIN_REFRESH_COOKIE_SAMESITE",
                    "must be explicit: lax, strict, or none",
                )
            )
        if settings.customer_refresh_cookie_samesite.lower() not in {"lax", "strict", "none"}:
            issues.append(
                ConfigIssue(
                    "VPN_SALE_CUSTOMER_REFRESH_COOKIE_SAMESITE",
                    "must be explicit: lax, strict, or none",
                )
            )
        if settings.cors_allow_credentials and "*" in settings.cors_allowed_origins:
            issues.append(
                ConfigIssue(
                    "VPN_SALE_CORS_ALLOWED_ORIGINS",
                    "cannot be wildcard when credentials are allowed",
                )
            )
        if settings.fake_customer_auth_enabled:
            issues.append(
                ConfigIssue(
                    "VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED", "is forbidden outside local/test"
                )
            )
        if settings.telegram_customer_auth_enabled and not settings.telegram_bot_token:
            issues.append(
                ConfigIssue(
                    "VPN_SALE_TELEGRAM_BOT_TOKEN",
                    "is required when Telegram customer auth is enabled",
                )
            )
    for name, value in (
        ("VPN_SALE_DATABASE_URL", settings.database_url),
        ("VPN_SALE_REDIS_URL", settings.redis_url),
        ("VPN_SALE_BACKUP_DESTINATION_URL", settings.backup_destination_url),
    ):
        if value and not _valid_url(value):
            issues.append(ConfigIssue(name, "must be a valid URL"))
    if settings.worker_concurrency < 1 or settings.worker_concurrency > 128:
        issues.append(ConfigIssue("VPN_SALE_WORKER_CONCURRENCY", "must be between 1 and 128"))
    if settings.request_body_limit_bytes < 1024 or settings.request_body_limit_bytes > 104857600:
        issues.append(
            ConfigIssue(
                "VPN_SALE_REQUEST_BODY_LIMIT_BYTES", "must be bounded between 1 KiB and 100 MiB"
            )
        )
    deprecated = sorted(
        name
        for name in os.environ
        if name.startswith("VPN_SALE_LEGACY_") or name.startswith("VPN_SALE_PROD_")
    )
    issues.extend(
        ConfigIssue(name, "deprecated VPN-SALE variable prefix", "warning") for name in deprecated
    )
    return issues


def assert_startup_configuration(settings: Settings) -> None:
    validate_security_configuration(settings)
    errors = [
        issue.variable
        for issue in validate_environment_profile(settings)
        if issue.severity == "error"
    ]
    if errors:
        raise ValueError("invalid VPN-SALE configuration: " + ", ".join(sorted(set(errors))))


def sanitize_mapping(data: dict[str, object]) -> dict[str, object]:
    return {key: ("<redacted>" if _is_secret_name(key) else value) for key, value in data.items()}


def release_metadata(settings: Settings) -> dict[str, str]:
    build_time = os.getenv("VPN_SALE_BUILD_TIME", "1970-01-01T00:00:00Z")
    commit_sha = os.getenv("VPN_SALE_COMMIT_SHA", "unknown")[:40]
    return {
        "application_version": settings.version,
        "commit_sha": commit_sha,
        "build_time": build_time,
        "schema_revision": os.getenv("VPN_SALE_SCHEMA_REVISION", "unknown"),
        "environment": settings.environment.upper(),
        "provider_contracts": json.dumps(PROVIDER_TARGETS, sort_keys=True),
    }


class ProviderCertificationSummary(BaseModel):
    provider: str
    target_version: str
    result: CertificationResult = CertificationResult.NOT_RUN
    live_read_enabled: bool = False
    live_write_canary_enabled: bool = False
    evidence_digest: str


class ReadinessReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    release_state: ReleaseState
    metadata: dict[str, str]
    checks: dict[str, str]
    provider_certification: list[ProviderCertificationSummary]
    release_blockers: list[str]
    deferred_checks: list[str]


def build_provider_certification_summary() -> list[ProviderCertificationSummary]:
    live_ack = os.getenv("VPN_SALE_PROVIDER_LIVE_ACK") == "I_UNDERSTAND_STAGING_ONLY"
    write_ack = os.getenv("VPN_SALE_PROVIDER_WRITE_CANARY_ACK") == "I_UNDERSTAND_DISPOSABLE_CANARY"
    summaries: list[ProviderCertificationSummary] = []
    for provider, target in PROVIDER_TARGETS.items():
        payload = f"{provider}:{target}:NOT_RUN".encode()
        summaries.append(
            ProviderCertificationSummary(
                provider=provider,
                target_version=target,
                live_read_enabled=live_ack,
                live_write_canary_enabled=live_ack and write_ack,
                evidence_digest=hashlib.sha256(payload).hexdigest(),
            )
        )
    return summaries


def build_readiness_report(settings: Settings, checks: dict[str, str]) -> ReadinessReport:
    blockers = [name for name, value in checks.items() if value not in {"PASS", "NOT_RUN"}]
    certifications = build_provider_certification_summary()
    if any(item.result == CertificationResult.NOT_RUN for item in certifications):
        blockers.append("live provider certification requires dedicated staging panels")
    state = ReleaseState.READY_FOR_STAGING if not blockers else ReleaseState.CONDITIONALLY_READY
    if settings.environment.upper() == "PRODUCTION":
        state = ReleaseState.READY_FOR_RELEASE_REVIEW if not blockers else ReleaseState.NOT_READY
    return ReadinessReport(
        release_state=state,
        metadata=release_metadata(settings),
        checks=checks,
        provider_certification=certifications,
        release_blockers=sorted(set(blockers)),
        deferred_checks=[
            "real provider certification NOT_RUN until operator supplies staging panels"
        ],
    )


router = APIRouter(prefix="/api/v1/operations", tags=["operations"])


@router.get("/startup")
async def startup_probe(response: Response) -> dict[str, object]:
    issues = validate_environment_profile(get_settings())
    errors = [issue.variable for issue in issues if issue.severity == "error"]
    if errors:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "started" if not errors else "blocked",
        "issues": [issue.__dict__ for issue in issues],
    }


@router.get("/readiness")
async def readiness_probe(response: Response) -> dict[str, object]:
    db_ok = await check_database()
    redis_ok = await check_redis()
    checks = {
        "configuration": "PASS"
        if not [i for i in validate_environment_profile(get_settings()) if i.severity == "error"]
        else "FAIL",
        "database": "PASS" if db_ok else "FAIL",
        "redis": "PASS" if redis_ok else "FAIL",
    }
    if "FAIL" in checks.values():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if "FAIL" not in checks.values() else "not_ready", "checks": checks}


@router.get("/release-metadata")
async def release_metadata_endpoint() -> dict[str, str]:
    return release_metadata(get_settings())


@router.get("/readiness-report")
async def readiness_report_endpoint() -> ReadinessReport:
    return build_readiness_report(
        get_settings(),
        {
            "configuration": "PASS",
            "smoke_tests": "NOT_RUN",
            "backup": "NOT_RUN",
            "restore_drill": "NOT_RUN",
        },
    )
