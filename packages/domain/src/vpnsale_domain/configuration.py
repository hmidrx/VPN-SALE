from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from string import Formatter
from typing import Any
from urllib.parse import urlparse

SAFE_SCHEMA_VERSION = 1
MAX_TEMPLATE_LENGTH = 1200
SAFE_ACTIONS = frozenset(
    {
        "OPEN_STORE",
        "OPEN_WALLET",
        "OPEN_WALLET_TOPUP",
        "OPEN_ORDERS",
        "OPEN_PAYMENTS",
        "OPEN_PROFILE",
        "OPEN_SECURITY",
        "OPEN_MINI_APP",
        "SHOW_HELP",
        "SHOW_CONTACT",
        "GO_HOME",
        "GO_BACK",
    }
)
SAFE_DESTINATIONS = frozenset(
    {
        "HOME",
        "CATALOG",
        "WALLET",
        "ORDERS",
        "PAYMENTS",
        "PROFILE",
        "SECURITY",
        "MINI_APP",
        "LEGAL",
        "CONTACT",
    }
)
FEATURE_CODES = frozenset(
    {
        "storefront",
        "custom_plan_builder",
        "wallet",
        "wallet_top_up",
        "external_payment",
        "payment_methods_history",
        "invoices",
        "customer_web_navigation",
        "telegram_mini_app",
        "telegram_bot_menu_entries",
        "registration",
        "maintenance",
        "experimental_ui",
    }
)
PLACEHOLDERS: dict[str, frozenset[str]] = {
    "telegram.welcome": frozenset({"store_name", "customer_display_name", "support_username"}),
    "maintenance": frozenset({"store_name", "support_url", "business_hours"}),
    "generic_error": frozenset({"correlation_id"}),
    "customer.home": frozenset({"store_name", "customer_display_name"}),
}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
CODE = re.compile(r"^[A-Z0-9_]{2,64}$")
SECRET_LIKE = re.compile(r"(?i)(api[_-]?key|secret|token|password|bearer\s+[a-z0-9._-]+)")


class ConfigState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"
    PUBLISH_FAILED = "PUBLISH_FAILED"


class MediaState(StrEnum):
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"
    ARCHIVED = "ARCHIVED"


class Namespace(StrEnum):
    BRAND = "BRAND"
    THEME = "THEME"
    PUBLIC_CONTACT = "PUBLIC_CONTACT"
    PUBLIC_LEGAL = "PUBLIC_LEGAL"
    CUSTOMER_WEB = "CUSTOMER_WEB"
    TELEGRAM_MINI_APP = "TELEGRAM_MINI_APP"
    TELEGRAM_BOT = "TELEGRAM_BOT"
    CONTENT_TEMPLATES = "CONTENT_TEMPLATES"
    FEATURE_FLAGS = "FEATURE_FLAGS"
    CUSTOMER_NAVIGATION = "CUSTOMER_NAVIGATION"
    TELEGRAM_MENU = "TELEGRAM_MENU"
    MAINTENANCE = "MAINTENANCE"
    MEDIA_ASSETS = "MEDIA_ASSETS"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "ERROR"
    path: str = "$"


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(i.severity == "ERROR" for i in self.issues)


def _issue(code: str, msg: str, path: str = "$") -> ValidationIssue:
    return ValidationIssue(code, msg, "ERROR", path)


def validate_public_url(value: str | None, *, allow_empty: bool = True) -> ValidationIssue | None:
    if not value:
        return None if allow_empty else _issue("url.required", "URL is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return _issue("url.unsafe_scheme", "Only http and https URLs with a host are allowed")
    if parsed.username or parsed.password:
        return _issue("url.credentials", "URLs must not contain credentials")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        return _issue("url.insecure", "HTTP is only allowed for local development hosts")
    return None


def validate_template(code: str, text: str) -> ValidationResult:
    issues: list[ValidationIssue] = []
    allowed = PLACEHOLDERS.get(code, frozenset())
    if len(text) > MAX_TEMPLATE_LENGTH:
        issues.append(_issue("template.too_long", "Template is too long"))
    if any(x in text.lower() for x in ("<script", "{{", "{%", "__import__", "eval(", "select ")):
        issues.append(_issue("template.executable", "Executable template syntax is not allowed"))
    for _, name, spec, conv in Formatter().parse(text):
        if name and (name not in allowed or "." in name or "[" in name or spec or conv):
            issues.append(_issue("template.placeholder", f"Placeholder {name} is not registered"))
    return ValidationResult(tuple(issues))


def render_template(code: str, text: str, values: dict[str, object], *, destination: str) -> str:
    if not validate_template(code, text).ok:
        text = compiled_defaults()["content_templates"][code]["fa"]
    allowed = PLACEHOLDERS.get(code, frozenset())
    safe = {k: html.escape(str(values.get(k, ""))) for k in allowed}
    return text.format(**safe)


def contrast_ratio(fg: str, bg: str) -> float:
    def lum(c: str) -> float:
        rgb = [int(c[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        vals = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]

    a, b = lum(fg), lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def stable_rollout(flag: str, subject: str, percentage: int, *, salt: str = "runtime") -> bool:
    if percentage <= 0:
        return False
    if percentage >= 100:
        return True
    digest = hashlib.sha256(f"{salt}:{flag}:{subject}".encode()).hexdigest()
    return int(digest[:8], 16) % 100 < percentage


def validate_snapshot(snapshot: dict[str, Any]) -> ValidationResult:
    issues: list[ValidationIssue] = []
    if snapshot.get("schema_version") != SAFE_SCHEMA_VERSION:
        issues.append(_issue("schema.unknown", "Unknown schema version"))
    for key in ("website_url", "support_url", "mini_app_url"):
        issue = validate_public_url(snapshot.get("brand", {}).get(key))
        if issue:
            issues.append(issue)
    for s in [str(snapshot)]:
        if SECRET_LIKE.search(s):
            issues.append(
                _issue("secret.detected", "Secret-like public configuration value rejected")
            )
        if any(x in s.lower() for x in ("javascript:", "data:", "file://", "<script")):
            issues.append(_issue("injection.detected", "Executable content rejected"))
    theme = snapshot.get("theme", {})
    for mode in ("light", "dark"):
        tokens = theme.get(mode, {})
        for name, val in tokens.items():
            if name.endswith("_color") and not HEX_COLOR.match(str(val)):
                issues.append(_issue("theme.color", "Invalid color", f"$.theme.{mode}.{name}"))
        if (
            tokens.get("text_primary_color")
            and tokens.get("page_color")
            and contrast_ratio(tokens["text_primary_color"], tokens["page_color"]) < 4.5
        ):
            issues.append(
                _issue("theme.contrast", "Text contrast is below WCAG AA", f"$.theme.{mode}")
            )
    for code, t in snapshot.get("content_templates", {}).items():
        issues.extend(validate_template(code, t.get("fa", "")).issues)
    seen: set[object] = set()
    for item in snapshot.get("customer_navigation", []):
        c = item.get("code")
        if c in seen:
            issues.append(_issue("navigation.duplicate", "Duplicate navigation code"))
        seen.add(c)
        if item.get("destination") not in SAFE_DESTINATIONS:
            issues.append(_issue("navigation.destination", "Unregistered destination"))
        u = validate_public_url(item.get("external_url"))
        if u:
            issues.append(u)
    for button in snapshot.get("telegram_menu", []):
        if button.get("action") not in SAFE_ACTIONS:
            issues.append(_issue("telegram.action", "Unregistered Telegram action"))
        if str(button.get("callback_data", "")).startswith("cfg:") is False:
            issues.append(
                _issue("telegram.callback", "Callback data must be generated opaque cfg action")
            )
    flags = snapshot.get("feature_flags", {})
    for code, flag in flags.items():
        if code not in FEATURE_CODES:
            issues.append(_issue("flag.unknown", "Unknown feature flag"))
        pct = int(flag.get("rollout_percentage", 0))
        if pct < 0 or pct > 100:
            issues.append(_issue("flag.rollout", "Rollout percentage out of range"))
        for dep in flag.get("dependencies", []):
            if dep not in flags:
                issues.append(_issue("flag.dependency", "Missing flag dependency"))
    return ValidationResult(tuple(issues))


def compiled_defaults() -> dict[str, Any]:
    return {
        "schema_version": SAFE_SCHEMA_VERSION,
        "brand": {
            "store_name": {"fa": "فروشگاه امن", "en": "Secure Store"},
            "short_name": "VPN-SALE",
            "tagline": {"fa": "دسترسی امن و پایدار", "en": "Safe and reliable access"},
            "support_username": "@support",
            "support_url": "https://example.invalid/support",
            "website_url": "https://example.invalid",
            "mini_app_url": "https://example.invalid/app",
        },
        "theme": {
            "light": {
                "page_color": "#ffffff",
                "surface_color": "#f8fafc",
                "text_primary_color": "#0f172a",
                "primary_color": "#2563eb",
                "focus_ring_color": "#f59e0b",
            },
            "dark": {
                "page_color": "#020617",
                "surface_color": "#0f172a",
                "text_primary_color": "#f8fafc",
                "primary_color": "#60a5fa",
                "focus_ring_color": "#fbbf24",
            },
            "radius": "md",
            "font_family": "Vazirmatn",
            "motion": "reduced-supported",
        },
        "content_templates": {
            "telegram.welcome": {
                "fa": "سلام {customer_display_name}، به {store_name} خوش آمدید.",
                "en": "Welcome to {store_name}, {customer_display_name}.",
            },
            "maintenance": {
                "fa": "{store_name} در حال نگهداری است. {business_hours}",
                "en": "{store_name} is under maintenance.",
            },
            "generic_error": {
                "fa": "خطای امن. شناسه: {correlation_id}",
                "en": "Safe error. Reference: {correlation_id}",
            },
            "customer.home": {"fa": "به {store_name} خوش آمدید", "en": "Welcome to {store_name}"},
        },
        "feature_flags": {
            code: {
                "enabled": code
                in {
                    "storefront",
                    "wallet",
                    "customer_web_navigation",
                    "telegram_mini_app",
                    "telegram_bot_menu_entries",
                },
                "safe_default": False,
                "owner": "platform",
                "description": code,
                "rollout_percentage": 100,
                "dependencies": [],
            }
            for code in FEATURE_CODES
        },
        "customer_navigation": [
            {
                "code": "HOME",
                "label": {"fa": "خانه", "en": "Home"},
                "destination": "HOME",
                "order": 1,
            },
            {
                "code": "WALLET",
                "label": {"fa": "کیف پول", "en": "Wallet"},
                "destination": "WALLET",
                "order": 2,
            },
        ],
        "telegram_menu": [
            {
                "code": "GO_HOME",
                "label": {"fa": "خانه", "en": "Home"},
                "action": "GO_HOME",
                "callback_data": "cfg:GO_HOME",
            },
            {
                "code": "OPEN_WALLET",
                "label": {"fa": "کیف پول", "en": "Wallet"},
                "action": "OPEN_WALLET",
                "callback_data": "cfg:OPEN_WALLET",
            },
        ],
        "maintenance": {
            "global": False,
            "customer_web": False,
            "telegram_bot": False,
            "mini_app": False,
            "payment_creation": False,
        },
    }


@dataclass
class Release:
    reference: str
    snapshot: dict[str, Any]
    state: ConfigState
    version: int
    published_at: datetime | None = None
    superseded_by: str | None = None


@dataclass
class Draft:
    reference: str
    snapshot: dict[str, Any] = field(default_factory=compiled_defaults)
    version: int = 1
    state: ConfigState = ConfigState.DRAFT

    def update_section(self, section: str, value: Any, expected_version: int) -> None:
        if expected_version != self.version:
            raise ValueError("stale_version")
        if section not in self.snapshot:
            raise ValueError("unknown_section")
        self.snapshot[section] = value
        self.version += 1

    def validate(self) -> ValidationResult:
        result = validate_snapshot(self.snapshot)
        self.state = ConfigState.READY_FOR_REVIEW if result.ok else ConfigState.VALIDATION_FAILED
        return result


def publish(draft: Draft, active: Release | None, *, now: datetime | None = None) -> Release:
    result = draft.validate()
    if not result.ok:
        raise ValueError("validation_failed")
    if active:
        active.state = ConfigState.SUPERSEDED
    return Release(
        reference="rel_" + hashlib.sha256(str(draft.snapshot).encode()).hexdigest()[:16],
        snapshot=draft.snapshot.copy(),
        state=ConfigState.PUBLISHED,
        version=(active.version + 1 if active else 1),
        published_at=now or datetime.now(UTC),
    )
