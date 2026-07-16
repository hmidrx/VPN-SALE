from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import unquote_to_bytes

_SAFE_KEYS = {"query_id", "user", "auth_date", "hash", "start_param"}


class TelegramInitDataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramUser:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    photo_url: str | None


@dataclass(frozen=True, slots=True)
class TelegramInitData:
    user: TelegramUser
    auth_date: datetime
    start_param: str | None


def _strict_unquote(value: str) -> str:
    try:
        return unquote_to_bytes(value).decode("utf-8", "strict")
    except Exception as exc:
        raise TelegramInitDataError("invalid Telegram authentication data") from exc


def _parse(raw: str, max_len: int) -> dict[str, str]:
    if not raw or len(raw) > max_len:
        raise TelegramInitDataError("invalid Telegram authentication data")
    values: dict[str, str] = {}
    for part in raw.split("&"):
        if not part or "=" not in part:
            raise TelegramInitDataError("invalid Telegram authentication data")
        key_raw, val_raw = part.split("=", 1)
        if "%" in key_raw and any(
            i + 2 >= len(key_raw)
            or not all(c in "0123456789abcdefABCDEF" for c in key_raw[i + 1 : i + 3])
            for i, c in enumerate(key_raw)
            if c == "%"
        ):
            raise TelegramInitDataError("invalid Telegram authentication data")
        key = _strict_unquote(key_raw)
        if key in values:
            raise TelegramInitDataError("invalid Telegram authentication data")
        values[key] = _strict_unquote(val_raw)
    return values


def _optional_text(value: object, max_len: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TelegramInitDataError("invalid Telegram authentication data")
    value = value.strip()
    return value[:max_len] or None


def _start(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) > 64 or not all(ch.isalnum() or ch in "_-" for ch in value):
        return None
    return value


class TelegramInitDataVerifier:
    def __init__(
        self, *, bot_token: str, max_age_seconds: int, future_skew_seconds: int, max_length: int
    ) -> None:
        if not bot_token:
            raise TelegramInitDataError("Telegram authentication is not configured")
        self.bot_token = bot_token
        self.max_age_seconds = max_age_seconds
        self.future_skew_seconds = future_skew_seconds
        self.max_length = max_length

    def verify(self, raw_init_data: str, *, now: datetime | None = None) -> TelegramInitData:
        now = now or datetime.now(UTC)
        params = _parse(raw_init_data, self.max_length)
        signature = params.get("hash")
        if not signature or "auth_date" not in params or "user" not in params:
            raise TelegramInitDataError("invalid Telegram authentication data")
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "hash")
        secret = hmac.new(b"WebAppData", self.bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise TelegramInitDataError("invalid Telegram authentication data")
        try:
            auth_ts = int(params["auth_date"])
        except ValueError as exc:
            raise TelegramInitDataError("invalid Telegram authentication data") from exc
        auth_date = datetime.fromtimestamp(auth_ts, UTC)
        if auth_date.timestamp() > now.timestamp() + self.future_skew_seconds:
            raise TelegramInitDataError("invalid Telegram authentication data")
        if now.timestamp() - auth_date.timestamp() > self.max_age_seconds:
            raise TelegramInitDataError("invalid Telegram authentication data")
        try:
            payload = json.loads(params["user"])
        except json.JSONDecodeError as exc:
            raise TelegramInitDataError("invalid Telegram authentication data") from exc
        if not isinstance(payload, dict):
            raise TelegramInitDataError("invalid Telegram authentication data")
        payload_t = cast(dict[str, object], payload)
        telegram_id = payload_t.get("id")
        if not isinstance(telegram_id, int) or telegram_id <= 0 or telegram_id > 2**63 - 1:
            raise TelegramInitDataError("invalid Telegram authentication data")
        first = _optional_text(payload_t.get("first_name"), 128)
        last = _optional_text(payload_t.get("last_name"), 128)
        username = _optional_text(payload_t.get("username"), 32)
        language = _optional_text(payload_t.get("language_code"), 16)
        photo = _optional_text(payload_t.get("photo_url"), 512)
        return TelegramInitData(
            user=TelegramUser(telegram_id, username, first, last, language, photo),
            auth_date=auth_date,
            start_param=_start(params.get("start_param")),
        )
