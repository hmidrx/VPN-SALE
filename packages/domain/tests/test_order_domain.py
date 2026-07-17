import pytest
from vpnsale_domain.orders import InvoiceTotals, OrderDomainError, require_order_transition


def test_order_transition_to_ready_requires_paid_path():
    require_order_transition("PAYMENT_RESERVED", "PAID")
    require_order_transition("PAID", "READY_FOR_FULFILLMENT")
    with pytest.raises(OrderDomainError):
        require_order_transition("PAYMENT_RESERVED", "READY_FOR_FULFILLMENT")


def test_invoice_totals_are_integer_rial_and_match():
    InvoiceTotals(1000, 0, 0, 0, 1000).validate()
    with pytest.raises(OrderDomainError):
        InvoiceTotals(1000, 0, 0, 0, 999).validate()
