from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OrderDomainError(ValueError):
    pass


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAYMENT_RESERVED = "PAYMENT_RESERVED"
    PAID = "PAID"
    READY_FOR_FULFILLMENT = "READY_FOR_FULFILLMENT"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class OrderFinancialStatus(StrEnum):
    UNPAID = "UNPAID"
    RESERVED = "RESERVED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class OrderFulfillmentStatus(StrEnum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    CANCELLED = "CANCELLED"


class InvoiceStatus(StrEnum):
    ISSUED = "ISSUED"
    PAYMENT_RESERVED = "PAYMENT_RESERVED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class CheckoutStatus(StrEnum):
    FUNDS_RESERVED = "FUNDS_RESERVED"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class WalletPaymentStatus(StrEnum):
    RESERVED = "RESERVED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING_PAYMENT: {OrderStatus.PAYMENT_RESERVED, OrderStatus.CANCELLED},
    OrderStatus.PAYMENT_RESERVED: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.READY_FOR_FULFILLMENT, OrderStatus.REFUNDED},
    OrderStatus.READY_FOR_FULFILLMENT: {OrderStatus.REFUNDED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED: set(),
    OrderStatus.FAILED: set(),
}


def require_order_transition(current: str, target: str) -> None:
    source = OrderStatus(current)
    destination = OrderStatus(target)
    if destination not in ORDER_TRANSITIONS[source]:
        raise OrderDomainError(f"illegal order transition {current}->{target}")


@dataclass(frozen=True)
class InvoiceTotals:
    subtotal_rial: int
    adjustment_total_rial: int
    discount_total_rial: int
    tax_total_rial: int
    payable_total_rial: int

    def validate(self) -> None:
        values = [
            self.subtotal_rial,
            self.adjustment_total_rial,
            self.discount_total_rial,
            self.tax_total_rial,
            self.payable_total_rial,
        ]
        if any(isinstance(v, bool) for v in values):
            raise OrderDomainError("money must be integer rial")
        if any(v < 0 for v in values):
            raise OrderDomainError("money must be non-negative")
        expected = (
            self.subtotal_rial
            + self.adjustment_total_rial
            - self.discount_total_rial
            + self.tax_total_rial
        )
        if self.payable_total_rial <= 0 or expected != self.payable_total_rial:
            raise OrderDomainError("invoice totals mismatch")
