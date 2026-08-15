from __future__ import annotations

import base64
import json
from datetime import timedelta
from inspect import getsource

from platform_api.identity.security import EncryptedSecret, FernetSecretEncryptor
from platform_worker import service_activation
from platform_worker.main import build_service_activator
from platform_worker.real_activator import DatabaseSanaeiActivator
from platform_worker.service_activation import (
    BLOCKED_RETRY,
    DisabledActivator,
    FernetDeliveryCipher,
    retry_delay,
)


def _fernet_key(byte: bytes = b"k") -> str:
    return base64.urlsafe_b64encode(byte * 32).decode()


def test_activation_retry_is_bounded_and_blocked_work_is_not_hammered() -> None:
    assert retry_delay(1) == timedelta(seconds=15)
    assert retry_delay(100) == timedelta(hours=1)
    assert BLOCKED_RETRY == timedelta(hours=6)


def test_activation_claim_is_postgres_safe_and_provider_io_is_outside_claim() -> None:
    source = getsource(service_activation.ServiceActivationWorker)
    assert "with_for_update(skip_locked=True)" in source
    assert ".limit(MAX_BATCH)" in source
    assert source.index("self.activator.activate") > source.index("def _claim")
    assert "compensate_failed_fulfillment" not in source
    assert "refund" not in source.lower()


def test_delivery_links_are_encrypted_before_persistence() -> None:
    key = _fernet_key()
    cipher = FernetDeliveryCipher(key, "delivery-v1")
    synthetic_link = (
        "vless"
        + "://"
        + "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa@edge.example:443?security=tls#one"
    )
    links = (synthetic_link,)

    key_version, ciphertext, digest = cipher.encrypt_links(links)

    assert key_version == "delivery-v1"
    assert links[0] not in ciphertext
    plaintext = FernetSecretEncryptor(key, key_version).decrypt(
        EncryptedSecret(key_version, ciphertext)
    )
    parsed = json.loads(plaintext)
    assert parsed == {"links": list(links), "version": 1}
    assert len(digest) == 64


def test_production_composition_reaches_real_activator_only_when_writes_enabled() -> None:
    factory = object()
    assert isinstance(build_service_activator(factory, False), DisabledActivator)  # type: ignore[arg-type]
    assert isinstance(build_service_activator(factory, True), DatabaseSanaeiActivator)  # type: ignore[arg-type]


def test_active_transition_is_atomic_with_delivery_and_entitlement_clock() -> None:
    source = getsource(service_activation.ServiceActivationWorker._complete_success)
    delivery_write = source.index("ServiceDeliveryModel(")
    clock_write = source.index("FulfillmentEntitlementClockModel(")
    lifecycle_write = source.index('service.lifecycle = "ACTIVE"')
    commit = source.rindex("db.commit()")

    assert delivery_write < lifecycle_write < commit
    assert clock_write < lifecycle_write < commit
    assert 'attachment.verification_status = "VERIFIED"' in source
    assert 'delivery.status = "DELIVERED"' in source
