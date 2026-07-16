from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest

from platform_api.customer_auth.telegram import TelegramInitDataError, TelegramInitDataVerifier

TOKEN = "123:test-disposable-token"  # noqa: S105
NOW = datetime(2026, 7, 16, tzinfo=UTC)


def signed(
    user: object | None = None,
    *,
    auth_date: int | None = None,
    token: str = TOKEN,
    extra: dict[str, str] | None = None,
) -> str:
    if user is None:
        user = {
            "id": 42,
            "first_name": "علی",
            "last_name": "Tester",
            "username": "customer",
            "language_code": "fa",
        }
    params = {
        "auth_date": str(auth_date or int(NOW.timestamp())),
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    if extra:
        params.update(extra)
    data = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
    return "&".join(f"{quote(k)}={quote(v)}" for k, v in params.items())


def verifier(max_length: int = 4096) -> TelegramInitDataVerifier:
    return TelegramInitDataVerifier(
        bot_token=TOKEN, max_age_seconds=60, future_skew_seconds=10, max_length=max_length
    )


def test_valid_unicode_and_missing_optional_fields() -> None:
    result = verifier().verify(
        signed({"id": 42, "first_name": "ژاله", "last_name": "Иванова"}), now=NOW
    )
    assert result.user.telegram_user_id == 42
    assert result.user.username is None
    assert result.user.language_code is None


@pytest.mark.parametrize(
    "raw",
    [
        signed().replace("42", "43"),
        signed(token="wrong"),  # noqa: S106
        signed() + "&user=x",
        "bad=%ZZ",
        "auth_date=1&hash=x",
        signed(user="nope"),
        signed(user={"id": "42"}),
        signed(user={"id": 0}),
        signed(user={"id": 2**63}),
        signed(user={"id": 42, "first_name": 5}),
    ],
)
def test_invalid_inputs(raw: str) -> None:
    with pytest.raises(TelegramInitDataError):
        verifier().verify(raw, now=NOW)


def test_expired_future_missing_hash_missing_user_and_oversized() -> None:
    for raw in [
        signed(auth_date=int((NOW - timedelta(seconds=61)).timestamp())),
        signed(auth_date=int((NOW + timedelta(seconds=11)).timestamp())),
        signed().replace("hash=", "x="),
        signed().split("&user=", 1)[0] + "&hash=x",
        signed() + ("a" * 4096),
    ]:
        with pytest.raises(TelegramInitDataError):
            verifier().verify(raw, now=NOW)


def test_raw_init_data_absent_from_error_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    raw = signed().replace("42", "99")
    with caplog.at_level(logging.INFO), pytest.raises(TelegramInitDataError) as exc:
        verifier().verify(raw, now=NOW)
    assert raw not in str(exc.value)
    assert raw not in caplog.text
