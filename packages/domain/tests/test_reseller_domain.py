from datetime import UTC, datetime

import pytest
from vpnsale_domain.resellers import (
    CreditFacility,
    PriceScope,
    PricingRuleKind,
    ResellerDomainError,
    ResellerPricingRule,
    ResellerQuotaPolicy,
    evaluate_reseller_price,
    render_remark_template,
    require_reseller_transition,
)


def test_reseller_lifecycle_allows_only_legal_transitions() -> None:
    require_reseller_transition("DRAFT", "PENDING_REVIEW")
    require_reseller_transition("PENDING_REVIEW", "ACTIVE")
    require_reseller_transition("ACTIVE", "SUSPENDED")
    with pytest.raises(ResellerDomainError):
        require_reseller_transition("DRAFT", "ACTIVE")


def test_pricing_precedence_floor_and_integer_discount() -> None:
    rules = [
        ResellerPricingRule(
            PricingRuleKind.PERCENT_DISCOUNT,
            20,
            PriceScope.PURCHASE,
            percent_bps=5000,
            minimum_price_rial=700,
        ),
        ResellerPricingRule(
            PricingRuleKind.EXACT,
            10,
            PriceScope.PURCHASE,
            exact_amount_rial=500,
            minimum_price_rial=800,
        ),
    ]
    result = evaluate_reseller_price(1_000, rules)
    assert result.final_wholesale_rial == 800
    assert result.discount_rial == 200
    assert result.explanation == ("base_price", "EXACT", "floor_enforced")


def test_ambiguous_overlapping_rules_are_rejected() -> None:
    rules = [
        ResellerPricingRule(
            PricingRuleKind.FIXED_DISCOUNT, 1, PriceScope.PURCHASE, fixed_discount_rial=1
        ),
        ResellerPricingRule(
            PricingRuleKind.PERCENT_DISCOUNT, 1, PriceScope.PURCHASE, percent_bps=100
        ),
    ]
    with pytest.raises(ResellerDomainError):
        evaluate_reseller_price(1_000, rules)


def test_credit_facility_cannot_exceed_limit() -> None:
    facility = CreditFacility(1_000, 900, False, datetime.now(UTC))
    with pytest.raises(ResellerDomainError):
        facility.reserve(101)
    assert facility.reserve(100).utilized_rial == 1_000


def test_stricter_quota_override_wins() -> None:
    tier = ResellerQuotaPolicy(100, 30, 1_000, 30_000, 10, 100, 5_000, 5_000, True)
    override = ResellerQuotaPolicy(10, 99, 2_000, 20_000, 1, 99, 1_000, 2_000, False)
    effective = tier.stricter_with(override)
    assert effective.max_managed_customers == 10
    assert effective.daily_order_count == 1
    assert not effective.custom_remarks_allowed


def test_safe_remark_template_preview_rejects_unsafe_content() -> None:
    assert (
        render_remark_template(
            "{reseller_brand}-{customer_label}", {"reseller_brand": "برند", "customer_label": "A1"}
        )
        == "برند-A1"
    )
    for template in ["http://evil", "{unknown}", "line\nbreak", "<script>"]:
        with pytest.raises(ResellerDomainError):
            render_remark_template(template, {})
