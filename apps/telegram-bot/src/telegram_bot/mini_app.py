from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, urljoin, urlparse


class MiniAppRoute(StrEnum):
    HOME = "home"
    PROFILE = "profile"
    SECURITY = "security"
    WALLET = "wallet"
    SUPPORT = "support"
    EDUCATION = "education"
    STATUS = "status"


ROUTE_PATHS = {
    MiniAppRoute.HOME: "/",
    MiniAppRoute.PROFILE: "/profile",
    MiniAppRoute.SECURITY: "/security",
    MiniAppRoute.WALLET: "/wallet",
    MiniAppRoute.SUPPORT: "/support",
    MiniAppRoute.EDUCATION: "/education",
    MiniAppRoute.STATUS: "/status",
}
FORBIDDEN_QUERY = {
    "token",
    "access_token",
    "refresh_token",
    "initData",
    "init_data",
    "user_id",
    "uuid",
    "email",
}


@dataclass(frozen=True)
class MiniAppUrlBuilder:
    base_url: str
    allowed_hosts: tuple[str, ...]
    production_like: bool = False

    def build(self, route: MiniAppRoute) -> str:
        parsed = urlparse(self.base_url)
        if parsed.hostname not in self.allowed_hosts:
            raise ValueError("Mini App host is not allowlisted")
        if self.production_like and parsed.scheme != "https":
            raise ValueError("Mini App URL must use HTTPS in production")
        if parsed.query:
            keys = {key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
            if keys & FORBIDDEN_QUERY:
                raise ValueError("Mini App base URL contains forbidden query")
            raise ValueError("Mini App base URL must not contain query parameters")
        if route not in ROUTE_PATHS:
            raise ValueError("unsupported Mini App route")
        return urljoin(self.base_url.rstrip("/") + "/", ROUTE_PATHS[route].lstrip("/"))

    def manual_topup(self, reference: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,48}", reference):
            raise ValueError("invalid manual top-up reference")
        self.build(MiniAppRoute.HOME)
        return urljoin(self.base_url.rstrip("/") + "/", f"wallet/top-up/manual/{reference}")
