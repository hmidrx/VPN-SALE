from pathlib import Path

from vpnsale_domain.manual_topups import approval_amounts, customer_safe_text

ROOT = Path(__file__).parents[1] / "src" / "platform_api"


def test_manual_topup_routes_and_security_contract_are_registered() -> None:
    source = (ROOT / "manual_topups.py").read_text()
    for route in (
        '@customer_router.post("")',
        '@customer_router.get("")',
        '@customer_router.get("/{reference}/destination")',
        '@customer_router.get("/{reference}")',
        '@customer_router.post("/{reference}/receipts")',
        '@customer_router.get("/{reference}/receipt")',
        '@customer_router.post("/{reference}/cancel")',
        '@admin_router.get("")',
        '@admin_router.get("/{reference}")',
        '@admin_router.get("/{reference}/receipt")',
        '@admin_router.post("/{reference}/request-resubmission")',
        '@admin_router.post("/{reference}/reject")',
        '@admin_router.post("/{reference}/approve")',
        '@admin_router.post("/{reference}/messages")',
    ):
        assert route in source
    ordinary_customer_dto = source[
        source.index("def _customer_dto(") : source.index("def _destination_settings(")
    ]
    assert "card_number" not in ordinary_customer_dto
    forbidden = ("destination_card", "public_url", "PaymentSettlement")
    assert not any(value in source for value in forbidden)


def test_approval_amounts_are_exact_and_overflow_checked() -> None:
    assert approval_amounts(1_000_000, 500_000) == (1_000_000, 500_000, 1_500_000)
    try:
        approval_amounts(9_223_372_036_854_775_807, 1)
    except ValueError as error:
        assert "integer range" in str(error)
    else:
        raise AssertionError("overflow accepted")


def test_customer_messages_reject_card_and_iban_data() -> None:
    for unsafe in ("6037 9912 3456 7890", "IR12 3456 7890 1234 5678 9012 34"):
        try:
            customer_safe_text(unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError("banking data accepted")
