import asyncio
import hmac
import json

import pytest
from payment_adapters import (
    AdapterEnvironment,
    AdapterRegistryError,
    FakePaymentAdapter,
    PaymentAdapterRegistry,
)
from payment_adapters.contracts import CreatePaymentRequest
from vpnsale_domain.payments import PaymentAmount, ProviderPaymentStatus


def test_fake_adapter_contract_success_and_webhook_signature() -> None:
    asyncio.run(_assert_fake_adapter_contract_success_and_webhook_signature())


async def _assert_fake_adapter_contract_success_and_webhook_signature() -> None:
    adapter = FakePaymentAdapter()
    created = await adapter.create_payment(
        CreatePaymentRequest(
            "pi",
            "100000",
            PaymentAmount(100000),
            "https://app/return",
            "https://app/webhook",
            "idem",
        )
    )
    assert created.provider_payment_reference == "fakepay_100000"
    verified = await adapter.verify_payment(created.provider_payment_reference)
    assert verified.status == ProviderPaymentStatus.SUCCEEDED
    assert verified.amount.amount_rial == 100000
    body = json.dumps(
        {"payment_ref": created.provider_payment_reference, "status": "SUCCEEDED"}
    ).encode()
    sig = hmac.digest(adapter.signing_secret.encode(), body, "sha256").hex()
    assert (
        await adapter.verify_webhook(body, {"x-fake-signature": sig, "x-fake-event": "evt_1"})
    ).valid
    assert not (await adapter.verify_webhook(body, {"x-fake-signature": "bad"})).valid


def test_registry_rejects_unknown_and_fake_in_production() -> None:
    registry = PaymentAdapterRegistry(AdapterEnvironment.TEST)
    registry.register(FakePaymentAdapter())
    assert registry.get("fake", "v1").capabilities().provider_code == "fake"
    with pytest.raises(AdapterRegistryError):
        registry.get("fake", "v2")
    with pytest.raises(AdapterRegistryError):
        PaymentAdapterRegistry(AdapterEnvironment.PRODUCTION).register(FakePaymentAdapter())
