from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException, Response

from platform_api import telegram_topup_destination_internal as destination_api
from platform_api.config import Settings
from platform_api.identity.security import EncryptedSecret


class FakeEncryptor:
    def decrypt(self, secret: EncryptedSecret) -> str:
        values = {
            "encrypted-card": "6037991234567890",
            "encrypted-holder": "فروشگاه تست",
        }
        return values[secret.ciphertext]


class FakeDb:
    def __init__(self, destination: object | None) -> None:
        self.destination = destination

    def get(self, model: object, identifier: str) -> object | None:
        assert model is destination_api.ManualTopupDestinationVersionModel
        assert identifier == "dest-v1"
        return self.destination


def destination_row() -> SimpleNamespace:
    return SimpleNamespace(
        encryption_key_version="test-v1",
        encrypted_card_number="encrypted-card",
        encrypted_card_holder_name="encrypted-holder",
    )


def customer_a(_db: object, _subject: int) -> str:
    return "customer-a"


def customer_b(_db: object, _subject: int) -> str:
    return "customer-b"


def display_enabled(_db: object) -> SimpleNamespace:
    return SimpleNamespace(customer_display_enabled=True)


def display_disabled(_db: object) -> SimpleNamespace:
    return SimpleNamespace(customer_display_enabled=False)


def encryptor(_settings: Settings) -> FakeEncryptor:
    return FakeEncryptor()


def request_with_destination(_db: object, _reference: str, _customer_id: str) -> SimpleNamespace:
    return SimpleNamespace(destination_version_id="dest-v1")


def test_owned_request_returns_only_customer_safe_formatted_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def owned_request(_db: object, reference: str, customer_id: str) -> SimpleNamespace:
        captured.update(reference=reference, customer_id=customer_id)
        return SimpleNamespace(destination_version_id="dest-v1")

    monkeypatch.setattr(destination_api, "_customer_id", customer_a)
    monkeypatch.setattr(destination_api, "customer_manual_topup_request", owned_request)
    monkeypatch.setattr(
        destination_api, "customer_manual_topup_destination_settings", display_enabled
    )
    monkeypatch.setattr(destination_api, "_encryptor", encryptor)
    response = Response()

    result = destination_api.manual_topup_destination(
        "mtp-owned",
        response,
        cast(Any, None),
        cast(Any, FakeDb(destination_row())),
        Settings(),
        4242,
    )

    assert captured == {"reference": "mtp-owned", "customer_id": "customer-a"}
    assert result == {
        "mode": "DIRECT_CARD",
        "formatted_card_number": "6037-9912-3456-7890",
        "card_holder_name": "فروشگاه تست",
        "support_required": False,
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization, X-Telegram-Subject"
    assert "encrypted-card" not in str(result)


def test_foreign_request_cannot_reach_destination_decryption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_foreign(_db: object, _reference: str, customer_id: str) -> SimpleNamespace:
        assert customer_id == "customer-b"
        raise HTTPException(status_code=404, detail="manual top-up request not found")

    def fail_encryptor(_settings: Settings) -> FakeEncryptor:
        pytest.fail("foreign request must not reach decryption")

    monkeypatch.setattr(destination_api, "_customer_id", customer_b)
    monkeypatch.setattr(destination_api, "customer_manual_topup_request", reject_foreign)
    monkeypatch.setattr(destination_api, "_encryptor", fail_encryptor)

    with pytest.raises(HTTPException) as exc_info:
        destination_api.manual_topup_destination(
            "mtp-foreign",
            Response(),
            cast(Any, None),
            cast(Any, FakeDb(destination_row())),
            Settings(),
            5252,
        )
    assert exc_info.value.status_code == 404


def test_disabled_customer_display_returns_support_only_without_decryption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_encryptor(_settings: Settings) -> FakeEncryptor:
        pytest.fail("disabled destination must not be decrypted")

    monkeypatch.setattr(destination_api, "_customer_id", customer_a)
    monkeypatch.setattr(destination_api, "customer_manual_topup_request", request_with_destination)
    monkeypatch.setattr(
        destination_api, "customer_manual_topup_destination_settings", display_disabled
    )
    monkeypatch.setattr(destination_api, "_encryptor", fail_encryptor)

    result = destination_api.manual_topup_destination(
        "mtp-owned",
        Response(),
        cast(Any, None),
        cast(Any, FakeDb(destination_row())),
        Settings(),
        4242,
    )
    assert result == {"mode": "SUPPORT_ONLY", "support_required": True}
