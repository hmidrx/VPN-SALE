from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CallbackAction(StrEnum):
    NAVIGATE = "nav"
    BACK = "back"
    HOME = "home"
    REFRESH = "ref"
    RETRY = "retry"
    CANCEL_CONVERSATION = "cancel"
    CANCEL = "cancel"  # compatibility alias for existing menu callbacks
    SET_LANGUAGE = "lang"
    OPEN_WEB_APP = "web"
    MENU = "home"  # compatibility
    HELP = "help"
    LANGUAGE = "language"
    PRIVACY = "privacy"
    PROFILE = "profile"
    SECURITY = "security"
    OPEN_EDUCATION = "education"
    SEARCH_GUIDES = "guide_search"
    SHOW_FAQ = "faq"
    OPEN_STATUS_PAGE = "status"
    MY_SERVICES = "services"
    OPEN_SERVICE = "svc_open"
    OPEN_CONFIGS = "cfg_open"
    OPEN_SUBSCRIPTION = "sub_open"
    OPEN_SERVICE_GUIDE = "svc_guide"
    BUY_SERVICE = "buy"
    SELECT_PLAN = "plan"
    CONFIRM_PURCHASE = "buy_ok"
    PURCHASE_STATUS = "order"
    WALLET = "wallet"
    SUPPORT = "support"
    STATUS = "status"
    DISCOUNTS = "discounts"
    ANNOUNCEMENTS = "announcements"
    SETTINGS = "settings"
    TOP_UP = "topup"
    CONFIRM_TOP_UP = "topup_ok"
    SEND_RECEIPT = "receipt"
    LIST_MANUAL_TOPUPS = "topups"
    OPEN_MANUAL_TOPUP = "topup_open"
    CANCEL_MANUAL_TOPUP = "topup_cancel"
    RENEW = "renew"
    UPGRADE = "upgrade"
    EXTRA_TRAFFIC = "extra"
    REVOKE_SESSION = "revoke"
    CONFIRM_REVOKE = "confirm_revoke"
    TOGGLE_NOTIFICATION = "ntf"


@dataclass(frozen=True)
class BotCallback:
    action: CallbackAction
    value: str = ""
    version: str = "v1"

    def pack(self) -> str:
        data = f"b:{self.version}:{self.action.value}:{self.value}"
        if len(data.encode()) > 64:
            raise ValueError("callback data too long")
        return data

    @classmethod
    def parse(cls, data: str | None) -> BotCallback:
        if not data or len(data.encode()) > 64:
            raise ValueError("invalid callback data")
        parts = data.split(":", 3)
        if len(parts) != 4 or parts[0] != "b" or parts[1] not in {"v1", "v2"}:
            raise ValueError("unsupported callback data")
        return cls(action=CallbackAction(parts[2]), value=parts[3], version=parts[1])
