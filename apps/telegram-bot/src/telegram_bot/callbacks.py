from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CallbackAction(StrEnum):
    MENU = "menu"
    HELP = "help"
    LANGUAGE = "lang"
    PRIVACY = "privacy"
    PROFILE = "profile"
    SECURITY = "security"


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
        parts = data.split(":")
        if len(parts) != 4 or parts[0] != "b" or parts[1] != "v1":
            raise ValueError("unsupported callback data")
        return cls(action=CallbackAction(parts[2]), value=parts[3], version=parts[1])
