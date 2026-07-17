from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from vpnsale_domain.payments import NormalizedPaymentResult, PaymentAmount, ProviderPaymentStatus


class AdapterEnvironment(StrEnum):
    TEST = "test"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class PaymentActionType(StrEnum):
    REDIRECT = "REDIRECT"
    NONE = "NONE"


@dataclass(frozen=True)
class PaymentHealth:
    healthy: bool
    credential_configured: bool = False
    safe_message: str | None = None


@dataclass(frozen=True)
class AdapterCapabilities:
    provider_code: str
    adapter_version: str
    supports_redirect: bool
    supports_webhook: bool
    supports_refund: bool
    supports_query: bool


@dataclass(frozen=True)
class CreatePaymentRequest:
    intent_reference: str
    attempt_reference: str
    amount: PaymentAmount
    return_url: str
    webhook_url: str
    idempotency_key: str
    safe_metadata: Mapping[str, str] | None = None


@dataclass(frozen=True)
class CreatePaymentResult:
    provider_payment_reference: str
    action_type: PaymentActionType
    action_url: str | None
    status: ProviderPaymentStatus
    expires_at: datetime | None = None
    safe_metadata: Mapping[str, str | int | bool] | None = None


@dataclass(frozen=True)
class ParsedReturn:
    provider_payment_reference: str | None
    provider_transaction_reference: str | None
    safe_metadata: Mapping[str, str | int | bool]


@dataclass(frozen=True)
class WebhookVerificationResult:
    valid: bool
    provider_event_reference: str | None
    reason_code: str | None = None


@dataclass(frozen=True)
class ParsedWebhook:
    provider_payment_reference: str | None
    provider_transaction_reference: str | None
    status: ProviderPaymentStatus
    safe_metadata: Mapping[str, str | int | bool]


@dataclass(frozen=True)
class RefundRequest:
    settlement_reference: str
    refund_reference: str
    provider_transaction_reference: str
    amount: PaymentAmount
    idempotency_key: str


@dataclass(frozen=True)
class RefundResult:
    provider_refund_reference: str
    status: str
    amount: PaymentAmount
    safe_metadata: Mapping[str, str | int | bool] | None = None


class PaymentGatewayAdapter(Protocol):
    def capabilities(self) -> AdapterCapabilities: ...

    async def health_check(self) -> PaymentHealth: ...

    async def create_payment(self, request: CreatePaymentRequest) -> CreatePaymentResult: ...

    async def parse_return(self, payload: Mapping[str, str]) -> ParsedReturn: ...

    async def verify_payment(self, provider_payment_reference: str) -> NormalizedPaymentResult: ...

    async def query_payment(self, provider_payment_reference: str) -> NormalizedPaymentResult: ...

    async def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> WebhookVerificationResult: ...

    async def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> ParsedWebhook: ...

    async def create_refund(self, request: RefundRequest) -> RefundResult: ...

    async def query_refund(self, provider_refund_reference: str) -> RefundResult: ...
