# pyright: reportPrivateUsage=false
from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from platform_api.activation_models import ServiceDeliveryModel
from platform_api.config import Settings
from platform_api.delivery import _decrypt_delivery
from platform_api.identity.security import FernetSecretEncryptor


def _key(byte: bytes = b"d") -> str:
    return base64.urlsafe_b64encode(byte * 32).decode()


def _delivery(link: str, *, digest: str | None = None, key_version: str = "delivery-v1") -> tuple[
    ServiceDeliveryModel, Settings
]:
    key = _key()
    payload = json.dumps(
        {"version": 1, "links": [link]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    encrypted = FernetSecretEncryptor(key, key_version).encrypt(payload)
    row = ServiceDeliveryModel(
        service_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        format="URI_LIST",
        encrypted_payload=encrypted.ciphertext,
        encryption_key_version=key_version,
        payload_sha256=digest or hashlib.sha256(payload.encode()).hexdigest(),
        item_count=1,
        status="DELIVERED",
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
        delivered_at=datetime(2026, 8, 15, tzinfo=UTC),
    )
    settings = Settings(
        identity_encryption_key=key,
        identity_encryption_key_version=key_version,
    )
    return row, settings


def test_delivery_payload_round_trips_only_after_integrity_verification() -> None:
    link = "vless://aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa@edge.example:443?security=tls#service"
    row, settings = _delivery(link)

    assert link not in row.encrypted_payload
    assert _decrypt_delivery(row, settings) == (link,)


def test_delivery_payload_tamper_fails_closed() -> None:
    link = "vless://aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa@edge.example:443?security=tls#service"
    row, settings = _delivery(link, digest="0" * 64)

    with pytest.raises(HTTPException) as exc:
        _decrypt_delivery(row, settings)
    assert exc.value.status_code == 503
    assert exc.value.detail == {"code": "DELIVERY_INTEGRITY_FAILED"}


def test_delivery_key_version_mismatch_fails_closed() -> None:
    link = "vless://aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa@edge.example:443?security=tls#service"
    row, settings = _delivery(link)
    settings.identity_encryption_key_version = "delivery-v2"

    with pytest.raises(HTTPException) as exc:
        _decrypt_delivery(row, settings)
    assert exc.value.status_code == 503
    assert exc.value.detail == {"code": "DELIVERY_KEY_VERSION_UNAVAILABLE"}
