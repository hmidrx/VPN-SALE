from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from vpnsale_domain.payments import NormalizedPaymentResult, PaymentAmount, ProviderPaymentStatus

from .contracts import (
    AdapterCapabilities,
    CreatePaymentRequest,
    CreatePaymentResult,
    ParsedReturn,
    ParsedWebhook,
    PaymentActionType,
    PaymentHealth,
    RefundRequest,
    RefundResult,
    WebhookVerificationResult,
)


@dataclass(frozen=True)
class FakePaymentScenario:
    status: ProviderPaymentStatus = ProviderPaymentStatus.SUCCEEDED
    amount_delta_rial: int = 0
    currency: str = "IRR"
    delayed_settlement: bool = False
    refund_status: str = "SUCCEEDED"


@dataclass
class FakePaymentAdapter:
    scenarios: Mapping[str, FakePaymentScenario] | None = None
    signing_secret: str = "fake-dev-signing-token"  # noqa: S105 - deterministic non-production test key
    adapter_version: str = "v1"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities("fake", self.adapter_version, True, True, True, True)

    async def health_check(self) -> PaymentHealth:
        return PaymentHealth(healthy=True, credential_configured=True, safe_message="fake adapter")

    async def create_payment(self, request: CreatePaymentRequest) -> CreatePaymentResult:
        reference = f"fakepay_{request.attempt_reference}"
        return CreatePaymentResult(
            provider_payment_reference=reference,
            action_type=PaymentActionType.REDIRECT,
            action_url=f"https://fake-payments.local/redirect/{reference}",
            status=ProviderPaymentStatus.REQUIRES_CUSTOMER_ACTION,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            safe_metadata={"adapter": "fake"},
        )

    async def parse_return(self, payload: Mapping[str, str]) -> ParsedReturn:
        return ParsedReturn(
            provider_payment_reference=payload.get("payment_ref"),
            provider_transaction_reference=payload.get("tx_ref"),
            safe_metadata={"return_seen": True},
        )

    async def verify_payment(self, provider_payment_reference: str) -> NormalizedPaymentResult:
        scenario = (self.scenarios or {}).get(provider_payment_reference, FakePaymentScenario())
        base_amount = (
            int(provider_payment_reference.rsplit("_", 1)[-1])
            if provider_payment_reference.rsplit("_", 1)[-1].isdigit()
            else 100_000
        )
        status = ProviderPaymentStatus.PENDING if scenario.delayed_settlement else scenario.status
        return NormalizedPaymentResult(
            provider_transaction_reference=f"tx_{provider_payment_reference}",
            status=status,
            amount=PaymentAmount(base_amount + scenario.amount_delta_rial, scenario.currency),
            settled_at=datetime.now(UTC) if status == ProviderPaymentStatus.SUCCEEDED else None,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            refundable_amount_rial=base_amount if status == ProviderPaymentStatus.SUCCEEDED else 0,
            failure_category="fake_failure" if status == ProviderPaymentStatus.FAILED else None,
            safe_metadata={"adapter": "fake", "status": status.value},
        )

    async def query_payment(self, provider_payment_reference: str) -> NormalizedPaymentResult:
        return await self.verify_payment(provider_payment_reference)

    async def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> WebhookVerificationResult:
        expected = hmac.digest(self.signing_secret.encode(), raw_body, "sha256").hex()
        valid = hmac.compare_digest(headers.get("x-fake-signature", ""), expected)
        event_ref = headers.get("x-fake-event")
        return WebhookVerificationResult(
            valid=valid,
            provider_event_reference=event_ref,
            reason_code=None if valid else "WEBHOOK_SIGNATURE_INVALID",
        )

    async def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> ParsedWebhook:
        body = json.loads(raw_body.decode())
        return ParsedWebhook(
            provider_payment_reference=body.get("payment_ref"),
            provider_transaction_reference=body.get("tx_ref"),
            status=ProviderPaymentStatus(body.get("status", "UNKNOWN")),
            safe_metadata={"event": headers.get("x-fake-event", "unknown")},
        )

    async def create_refund(self, request: RefundRequest) -> RefundResult:
        scenario = (self.scenarios or {}).get(
            request.provider_transaction_reference, FakePaymentScenario()
        )
        return RefundResult(
            f"refund_{request.refund_reference}",
            scenario.refund_status,
            request.amount,
            {"adapter": "fake"},
        )

    async def query_refund(self, provider_refund_reference: str) -> RefundResult:
        return RefundResult(
            provider_refund_reference, "SUCCEEDED", PaymentAmount(100_000), {"adapter": "fake"}
        )
