from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from html import escape


class ScreenId(StrEnum):
    HOME = "home"
    BUY = "buy"
    SERVICES = "services"
    WALLET = "wallet"
    DISCOUNTS = "discounts"
    SUPPORT = "support"
    EDUCATION = "education"
    PROFILE = "profile"
    SETTINGS = "settings"
    STATUS = "status"
    ANNOUNCEMENTS = "announcements"
    LANGUAGE = "language"
    PRIVACY = "privacy"
    HELP = "help"


@dataclass(frozen=True)
class DashboardData:
    display_name: str = "مشتری"
    wallet_balance_minor: int | None = 0
    active_services: int | None = 0
    nearest_expiry: datetime | None = None
    open_tickets: int | None = 0
    maintenance_notice: str | None = None


@dataclass(frozen=True)
class RenderedScreen:
    text: str
    rows: list[list[dict[str, str]]]
    screen: ScreenId


PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_number(value: int) -> str:
    return f"{value:,}".translate(PERSIAN_DIGITS)


def safe_text(value: str | None, fallback: str = "—") -> str:
    cleaned = (value or "").strip()
    if len(cleaned) > 48:
        cleaned = cleaned[:47] + "…"
    return escape(cleaned or fallback, quote=True)


def safe_date(value: datetime | None, locale: str) -> str:
    if value is None:
        return "—"
    text = value.date().isoformat()
    return text.translate(PERSIAN_DIGITS) if locale == "fa" else text
