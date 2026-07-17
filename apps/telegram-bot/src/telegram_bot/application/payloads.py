from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

SAFE = re.compile(r"^[A-Za-z0-9_=-]{1,64}$")
ROUTES = {"home": "/", "profile": "/profile", "security": "/security"}


class PayloadKind(StrEnum):
    EMPTY = "empty"
    GENERIC = "generic"
    MINI_APP_ROUTE = "mini_app_route"
    FUTURE_CAMPAIGN = "future_campaign"
    FUTURE_SUPPORT = "future_support"
    INVALID = "invalid"


@dataclass(frozen=True)
class StartPayload:
    kind: PayloadKind
    value: str = ""
    valid: bool = True


def parse_start_payload(raw: str | None) -> StartPayload:
    if not raw:
        return StartPayload(PayloadKind.EMPTY)
    if len(raw) > 64 or not SAFE.fullmatch(raw) or ".." in raw:
        return StartPayload(PayloadKind.INVALID, valid=False)
    if raw.startswith("v1_app_"):
        route = raw.removeprefix("v1_app_")
        if route in ROUTES:
            return StartPayload(PayloadKind.MINI_APP_ROUTE, route)
        return StartPayload(PayloadKind.INVALID, valid=False)
    if raw.startswith("v1_campaign_"):
        return StartPayload(PayloadKind.FUTURE_CAMPAIGN, raw[:64])
    if raw.startswith("v1_support_"):
        return StartPayload(PayloadKind.FUTURE_SUPPORT, raw[:64])
    if raw.startswith("v1_"):
        return StartPayload(PayloadKind.GENERIC, raw[:64])
    return StartPayload(PayloadKind.INVALID, valid=False)
