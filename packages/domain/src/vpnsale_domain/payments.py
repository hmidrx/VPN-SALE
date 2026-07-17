from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

IRR = "IRR"
MAX_RIAL_AMOUNT = 9_999_999_999_999


class PaymentDomainError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PaymentPurpose(StrEnum):
    WALLET_TOPUP = "WALLET_TOPUP"
    ORDER_PAYMENT = "ORDER_PAYMENT"


class PaymentChannel(StrEnum):
    REDIRECT = "REDIRECT"
    WEBHOOK = "WEBHOOK"


class PaymentMethodStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"
    ARCHIVED = "ARCHIVED"


class PaymentIntentStatus(StrEnum):
    CREATED = "CREATED"
    REQUIRES_PROVIDER = "REQUIRES_PROVIDER"
    REQUIRES_CUSTOMER_ACTION = "REQUIRES_CUSTOMER_ACTION"
    PROCESSING = "PROCESSING"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class PaymentAttemptStatus(StrEnum):
    CREATED = "CREATED"
    PROVIDER_REQUESTED = "PROVIDER_REQUESTED"
    CUSTOMER_ACTION_REQUIRED = "CUSTOMER_ACTION_REQUIRED"
    RETURNED = "RETURNED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class ProviderPaymentStatus(StrEnum):
    PENDING = "PENDING"
    REQUIRES_CUSTOMER_ACTION = "REQUIRES_CUSTOMER_ACTION"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class RefundStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class WebhookInboxStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    RETRY = "RETRY"
    DEAD_LETTER = "DEAD_LETTER"


class ReconciliationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


INTENT_TRANSITIONS: Mapping[PaymentIntentStatus, frozenset[PaymentIntentStatus]] = MappingProxyType(
    {
        PaymentIntentStatus.CREATED: frozenset(
            {
                PaymentIntentStatus.REQUIRES_PROVIDER,
                PaymentIntentStatus.CANCELLED,
                PaymentIntentStatus.EXPIRED,
            }
        ),
        PaymentIntentStatus.REQUIRES_PROVIDER: frozenset(
            {
                PaymentIntentStatus.REQUIRES_CUSTOMER_ACTION,
                PaymentIntentStatus.PROCESSING,
                PaymentIntentStatus.FAILED,
                PaymentIntentStatus.EXPIRED,
            }
        ),
        PaymentIntentStatus.REQUIRES_CUSTOMER_ACTION: frozenset(
            {
                PaymentIntentStatus.PROCESSING,
                PaymentIntentStatus.REQUIRES_VERIFICATION,
                PaymentIntentStatus.FAILED,
                PaymentIntentStatus.CANCELLED,
                PaymentIntentStatus.EXPIRED,
            }
        ),
        PaymentIntentStatus.PROCESSING: frozenset(
            {
                PaymentIntentStatus.REQUIRES_VERIFICATION,
                PaymentIntentStatus.SUCCEEDED,
                PaymentIntentStatus.FAILED,
                PaymentIntentStatus.RECONCILIATION_REQUIRED,
            }
        ),
        PaymentIntentStatus.REQUIRES_VERIFICATION: frozenset(
            {
                PaymentIntentStatus.SUCCEEDED,
                PaymentIntentStatus.FAILED,
                PaymentIntentStatus.RECONCILIATION_REQUIRED,
            }
        ),
        PaymentIntentStatus.SUCCEEDED: frozenset(
            {PaymentIntentStatus.REFUND_PENDING, PaymentIntentStatus.REFUNDED}
        ),
        PaymentIntentStatus.REFUND_PENDING: frozenset(
            {PaymentIntentStatus.REFUNDED, PaymentIntentStatus.RECONCILIATION_REQUIRED}
        ),
        PaymentIntentStatus.FAILED: frozenset(),
        PaymentIntentStatus.CANCELLED: frozenset({PaymentIntentStatus.RECONCILIATION_REQUIRED}),
        PaymentIntentStatus.EXPIRED: frozenset({PaymentIntentStatus.RECONCILIATION_REQUIRED}),
        PaymentIntentStatus.REFUNDED: frozenset(),
        PaymentIntentStatus.RECONCILIATION_REQUIRED: frozenset(),
    }
)

ATTEMPT_TRANSITIONS: Mapping[PaymentAttemptStatus, frozenset[PaymentAttemptStatus]] = (
    MappingProxyType(
        {
            PaymentAttemptStatus.CREATED: frozenset(
                {
                    PaymentAttemptStatus.PROVIDER_REQUESTED,
                    PaymentAttemptStatus.CANCELLED,
                    PaymentAttemptStatus.EXPIRED,
                }
            ),
            PaymentAttemptStatus.PROVIDER_REQUESTED: frozenset(
                {
                    PaymentAttemptStatus.CUSTOMER_ACTION_REQUIRED,
                    PaymentAttemptStatus.VERIFICATION_PENDING,
                    PaymentAttemptStatus.VERIFIED_FAILURE,
                    PaymentAttemptStatus.EXPIRED,
                    PaymentAttemptStatus.UNKNOWN,
                }
            ),
            PaymentAttemptStatus.CUSTOMER_ACTION_REQUIRED: frozenset(
                {
                    PaymentAttemptStatus.RETURNED,
                    PaymentAttemptStatus.VERIFICATION_PENDING,
                    PaymentAttemptStatus.EXPIRED,
                    PaymentAttemptStatus.CANCELLED,
                }
            ),
            PaymentAttemptStatus.RETURNED: frozenset(
                {PaymentAttemptStatus.VERIFICATION_PENDING, PaymentAttemptStatus.VERIFIED_FAILURE}
            ),
            PaymentAttemptStatus.VERIFICATION_PENDING: frozenset(
                {
                    PaymentAttemptStatus.VERIFIED_SUCCESS,
                    PaymentAttemptStatus.VERIFIED_FAILURE,
                    PaymentAttemptStatus.UNKNOWN,
                }
            ),
            PaymentAttemptStatus.UNKNOWN: frozenset(
                {PaymentAttemptStatus.VERIFICATION_PENDING, PaymentAttemptStatus.VERIFIED_FAILURE}
            ),
            PaymentAttemptStatus.VERIFIED_SUCCESS: frozenset(),
            PaymentAttemptStatus.VERIFIED_FAILURE: frozenset(),
            PaymentAttemptStatus.EXPIRED: frozenset(),
            PaymentAttemptStatus.CANCELLED: frozenset(),
        }
    )
)


def require_intent_transition(current: str, target: str) -> None:
    source = PaymentIntentStatus(current)
    destination = PaymentIntentStatus(target)
    if destination not in INTENT_TRANSITIONS[source]:
        raise PaymentDomainError(
            "CONCURRENT_MODIFICATION", f"illegal payment intent transition {current}->{target}"
        )


def require_attempt_transition(current: str, target: str) -> None:
    source = PaymentAttemptStatus(current)
    destination = PaymentAttemptStatus(target)
    if destination not in ATTEMPT_TRANSITIONS[source]:
        raise PaymentDomainError(
            "CONCURRENT_MODIFICATION", f"illegal payment attempt transition {current}->{target}"
        )


@dataclass(frozen=True)
class PaymentAmount:
    amount_rial: int
    currency: str = IRR

    def __post_init__(self) -> None:
        if type(self.amount_rial) is not int:
            raise PaymentDomainError("PAYMENT_AMOUNT_MISMATCH", "amount must be integer rial")
        if self.amount_rial <= 0 or self.amount_rial > MAX_RIAL_AMOUNT:
            raise PaymentDomainError(
                "PAYMENT_AMOUNT_MISMATCH", "amount is outside supported bounds"
            )
        if self.currency != IRR:
            raise PaymentDomainError("PAYMENT_CURRENCY_MISMATCH", "only IRR is supported")


@dataclass(frozen=True)
class PaymentMethodPolicy:
    min_amount_rial: int
    max_amount_rial: int
    supported_purposes: frozenset[PaymentPurpose]
    supported_channels: frozenset[PaymentChannel]

    def validate(
        self, purpose: PaymentPurpose, channel: PaymentChannel, amount: PaymentAmount
    ) -> None:
        if purpose not in self.supported_purposes:
            raise PaymentDomainError(
                "PAYMENT_PURPOSE_UNSUPPORTED", "payment purpose is not supported"
            )
        if channel not in self.supported_channels:
            raise PaymentDomainError(
                "PAYMENT_METHOD_UNAVAILABLE", "payment channel is not supported"
            )
        if amount.amount_rial < self.min_amount_rial:
            raise PaymentDomainError("WALLET_TOPUP_BELOW_MINIMUM", "amount is below minimum")
        if amount.amount_rial > self.max_amount_rial:
            raise PaymentDomainError("WALLET_TOPUP_ABOVE_MAXIMUM", "amount is above maximum")


def require_method_available(status: PaymentMethodStatus, maintenance_mode: bool) -> None:
    if maintenance_mode or status == PaymentMethodStatus.MAINTENANCE:
        raise PaymentDomainError("PAYMENT_METHOD_MAINTENANCE", "payment method is in maintenance")
    if status != PaymentMethodStatus.ACTIVE:
        raise PaymentDomainError("PAYMENT_METHOD_UNAVAILABLE", "payment method is not active")


@dataclass(frozen=True)
class NormalizedPaymentResult:
    provider_transaction_reference: str
    status: ProviderPaymentStatus
    amount: PaymentAmount
    settled_at: datetime | None = None
    expires_at: datetime | None = None
    refundable_amount_rial: int = 0
    failure_category: str | None = None
    safe_metadata: Mapping[str, str | int | bool] | None = None


def validate_verified_result(intent_amount: PaymentAmount, result: NormalizedPaymentResult) -> None:
    if result.amount.amount_rial != intent_amount.amount_rial:
        raise PaymentDomainError("PAYMENT_AMOUNT_MISMATCH", "provider amount does not match intent")
    if result.amount.currency != intent_amount.currency:
        raise PaymentDomainError(
            "PAYMENT_CURRENCY_MISMATCH", "provider currency does not match intent"
        )
    if result.status != ProviderPaymentStatus.SUCCEEDED:
        raise PaymentDomainError("PAYMENT_VERIFICATION_FAILED", "provider did not verify success")


class RefundRequestStatus(StrEnum):
    REQUESTED = "REQUESTED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PROVIDER_PENDING = "PROVIDER_PENDING"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ReconciliationScope(StrEnum):
    PAYMENT_INTENT = "PAYMENT_INTENT"
    PAYMENT_ATTEMPT = "PAYMENT_ATTEMPT"
    PAYMENT_SETTLEMENT = "PAYMENT_SETTLEMENT"
    WALLET_TOPUP = "WALLET_TOPUP"
    EXTERNAL_ORDER_PAYMENT = "EXTERNAL_ORDER_PAYMENT"
    REFUND = "REFUND"
    WEBHOOK = "WEBHOOK"
    LATE_SETTLEMENT = "LATE_SETTLEMENT"
    UNAPPLIED_PAYMENT = "UNAPPLIED_PAYMENT"


class RepairEligibility(StrEnum):
    SAFE_DERIVED_STATE = "SAFE_DERIVED_STATE"
    MANUAL_REVIEW_ONLY = "MANUAL_REVIEW_ONLY"
    BLOCKED_CRITICAL = "BLOCKED_CRITICAL"


@dataclass(frozen=True)
class RefundEligibilityInput:
    settlement_amount_rial: int
    settlement_currency: str
    already_refunded_rial: int
    provider_supports_refund: bool
    trusted_settlement: bool
    purpose: PaymentPurpose
    order_refundable: bool = False
    wallet_cash_available_rial: int = 0
    wallet_cash_reserved_rial: int = 0
    wallet_cash_credit_from_topup_rial: int = 0


@dataclass(frozen=True)
class RefundEligibility:
    eligible: bool
    amount: PaymentAmount | None
    reason_code: str | None
    requires_approval: bool


def calculate_refund_eligibility(
    data: RefundEligibilityInput, *, high_risk_threshold_rial: int = 50_000_000
) -> RefundEligibility:
    amount = PaymentAmount(data.settlement_amount_rial, data.settlement_currency)
    if not data.trusted_settlement:
        return RefundEligibility(False, None, "SETTLEMENT_NOT_TRUSTED", False)
    if not data.provider_supports_refund:
        return RefundEligibility(False, None, "PROVIDER_REFUND_UNSUPPORTED", False)
    remaining = data.settlement_amount_rial - data.already_refunded_rial
    if remaining != data.settlement_amount_rial or remaining <= 0:
        return RefundEligibility(False, None, "REFUND_ALREADY_EXISTS", False)
    if data.purpose == PaymentPurpose.ORDER_PAYMENT:
        if not data.order_refundable:
            return RefundEligibility(False, None, "ORDER_NOT_REFUNDABLE", False)
    elif data.purpose == PaymentPurpose.WALLET_TOPUP:
        unreserved_cash = data.wallet_cash_available_rial - data.wallet_cash_reserved_rial
        topup_cash = min(data.wallet_cash_credit_from_topup_rial, unreserved_cash)
        if topup_cash < data.settlement_amount_rial:
            return RefundEligibility(False, None, "INSUFFICIENT_UNRESERVED_CASH_COVERAGE", False)
    else:  # pragma: no cover - future enum protection
        return RefundEligibility(False, None, "UNSUPPORTED_REFUND_PURPOSE", False)
    return RefundEligibility(True, amount, None, amount.amount_rial >= high_risk_threshold_rial)


def require_creator_approver_separation(creator_admin_id: str, approver_admin_id: str) -> None:
    if creator_admin_id == approver_admin_id:
        raise PaymentDomainError("REFUND_SELF_APPROVAL_DENIED", "creator cannot approve refund")


def validate_refund_provider_result(
    expected: PaymentAmount,
    original_provider_transaction_reference: str,
    result_amount: PaymentAmount,
    result_status: str,
    result_original_reference: str | None = None,
) -> None:
    if result_status != "SUCCEEDED":
        raise PaymentDomainError(
            "REFUND_VERIFICATION_PENDING", "trusted refund success not verified"
        )
    if result_amount.amount_rial != expected.amount_rial:
        raise PaymentDomainError("REFUND_AMOUNT_MISMATCH", "provider refund amount mismatch")
    if result_amount.currency != expected.currency:
        raise PaymentDomainError("REFUND_CURRENCY_MISMATCH", "provider refund currency mismatch")
    if (
        result_original_reference
        and result_original_reference != original_provider_transaction_reference
    ):
        raise PaymentDomainError(
            "REFUND_ORIGINAL_REFERENCE_MISMATCH", "provider original reference mismatch"
        )


@dataclass(frozen=True)
class ReconciliationMismatch:
    code: str
    scope: ReconciliationScope
    severity: ReconciliationSeverity
    evidence: Mapping[str, str | int | bool]
    stored_state: Mapping[str, str | int | bool]
    expected_state: Mapping[str, str | int | bool]
    repair: RepairEligibility
    manual_review_required: bool


SAFE_REPAIR_CODES = frozenset(
    {
        "DERIVED_PAYMENT_STATUS_STALE",
        "PAID_INVOICE_PROJECTION_MISSING",
        "MISSING_READY_FOR_FULFILLMENT_OUTBOX",
        "WALLET_PROJECTION_MISMATCH",
    }
)

CRITICAL_REPAIR_BLOCKED_CODES = frozenset(
    {
        "PROVIDER_AMOUNT_MISMATCH",
        "PROVIDER_CURRENCY_MISMATCH",
        "DUPLICATE_SETTLEMENT",
        "DUPLICATE_REFUND_EFFECT",
        "INVALID_SIGNATURE_WEBHOOK_FINANCIAL_EFFECT",
        "UNBALANCED_SETTLEMENT_JOURNAL",
        "PROVIDER_REFERENCE_REUSE",
        "UNCERTAIN_LATE_SETTLEMENT",
        "OWNERSHIP_MISMATCH",
    }
)


def classify_repair(code: str) -> RepairEligibility:
    if code in SAFE_REPAIR_CODES:
        return RepairEligibility.SAFE_DERIVED_STATE
    if code in CRITICAL_REPAIR_BLOCKED_CODES:
        return RepairEligibility.BLOCKED_CRITICAL
    return RepairEligibility.MANUAL_REVIEW_ONLY


def make_mismatch(
    code: str,
    scope: ReconciliationScope,
    severity: ReconciliationSeverity,
    evidence: Mapping[str, str | int | bool],
    stored_state: Mapping[str, str | int | bool],
    expected_state: Mapping[str, str | int | bool],
) -> ReconciliationMismatch:
    repair = classify_repair(code)
    return ReconciliationMismatch(
        code,
        scope,
        severity,
        MappingProxyType(dict(evidence)),
        MappingProxyType(dict(stored_state)),
        MappingProxyType(dict(expected_state)),
        repair,
        repair != RepairEligibility.SAFE_DERIVED_STATE,
    )
