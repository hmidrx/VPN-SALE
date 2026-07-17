from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from vpnsale_domain.catalog import (
    CatalogError,
    CatalogOption,
    DeviceLimit,
    DurationDays,
    FulfillmentRequirement,
    InvalidCatalogTransition,
    LocalizedText,
    Money,
    OperationType,
    PlanConstraint,
    PlanOptions,
    PlanSelection,
    PriceListVersion,
    PriceRule,
    PriceRuleType,
    PricingEngine,
    PricingTier,
    ProductStatus,
    ProductType,
    ProductVersion,
    ProductVersionStatus,
    RangeConstraint,
    TrafficAmount,
    ensure_transition,
    validate_tiers,
)


def option(code: str) -> CatalogOption:
    return CatalogOption(code, (LocalizedText("fa", code),))


def version(product_type: ProductType = ProductType.CUSTOM_PLAN) -> ProductVersion:
    return ProductVersion(
        uuid4(),
        uuid4(),
        1,
        ProductVersionStatus.PUBLISHED,
        product_type,
        PlanOptions(
            RangeConstraint(10, 100, 10),
            RangeConstraint(30, 365, 30),
            RangeConstraint(1, 10, 1),
            (option("auto"), option("premium")),
            (option("standard"), option("gaming")),
            10 if product_type == ProductType.FIXED_PLAN else None,
            30 if product_type == ProductType.FIXED_PLAN else None,
            1 if product_type == ProductType.FIXED_PLAN else None,
        ),
        (PlanConstraint("LOCATION_MIN_DURATION", "premium", minimum_duration_days=60),),
        (FulfillmentRequirement("limit.traffic"),),
        datetime.now(UTC),
    )


def selection() -> PlanSelection:
    return PlanSelection(TrafficAmount(20), DurationDays(60), DeviceLimit(2), "premium", "gaming")


def price_list(*rules: PriceRule) -> PriceListVersion:
    return PriceListVersion(
        uuid4(),
        uuid4(),
        1,
        "IRR",
        datetime.now(UTC) - timedelta(days=1),
        None,
        10,
        True,
        None,
        rules,
    )


def test_money_uses_integer_rial_and_toman_display() -> None:
    assert Money(1250, "IRR").add(Money(750, "IRR")).amount == 2000
    assert Money(1250, "IRR").to_toman() == 125
    with pytest.raises(CatalogError):
        Money(-1)


def test_value_objects_reject_invalid_bounds() -> None:
    with pytest.raises(CatalogError):
        TrafficAmount(0)
    with pytest.raises(CatalogError):
        DurationDays(0)
    with pytest.raises(CatalogError):
        DeviceLimit(0)


def test_product_lifecycle_transitions_are_explicit() -> None:
    ensure_transition(ProductStatus.DRAFT, ProductStatus.ACTIVE)
    with pytest.raises(InvalidCatalogTransition):
        ensure_transition(ProductStatus.ARCHIVED, ProductStatus.ACTIVE)


def test_fixed_plan_requires_exact_template() -> None:
    fixed = version(ProductType.FIXED_PLAN)
    rules = price_list(PriceRule("base", PriceRuleType.FIXED_BASE, amount=1000))
    result = PricingEngine().quote(
        fixed,
        rules,
        PlanSelection(TrafficAmount(10), DurationDays(30), DeviceLimit(1), "auto", "standard"),
        OperationType.NEW_PURCHASE,
        datetime.now(UTC),
    )
    assert result.final.amount == 1000
    with pytest.raises(CatalogError):
        PricingEngine().quote(
            fixed, rules, selection(), OperationType.NEW_PURCHASE, datetime.now(UTC)
        )


def test_custom_plan_pricing_order_and_components() -> None:
    rules = price_list(
        PriceRule("base", PriceRuleType.FIXED_BASE, amount=1000, priority=1),
        PriceRule("traffic", PriceRuleType.PER_TRAFFIC_UNIT, amount=100, unit_size=10, priority=2),
        PriceRule("duration", PriceRuleType.PER_DURATION_UNIT, amount=50, unit_size=30, priority=3),
        PriceRule("devices", PriceRuleType.PER_DEVICE, amount=25, priority=4),
        PriceRule(
            "loc", PriceRuleType.LOCATION_SURCHARGE, amount=500, selector_code="premium", priority=5
        ),
        PriceRule(
            "quality",
            PriceRuleType.QUALITY_SURCHARGE,
            amount=250,
            selector_code="gaming",
            priority=6,
        ),
        PriceRule(
            "renewal",
            PriceRuleType.FIXED_ADJUSTMENT,
            amount=75,
            operation=OperationType.RENEWAL,
            priority=7,
        ),
        PriceRule("minimum", PriceRuleType.MINIMUM_FINAL, amount=3000, priority=8),
    )
    result = PricingEngine().quote(
        version(), rules, selection(), OperationType.RENEWAL, datetime.now(UTC)
    )
    assert [c.code for c in result.components] == [
        "base",
        "traffic",
        "duration",
        "devices",
        "loc",
        "quality",
        "renewal",
        "minimum",
    ]
    assert result.final.amount == 3000


def test_constraints_and_tiers_validate() -> None:
    with pytest.raises(CatalogError):
        PricingEngine().quote(
            version(),
            price_list(PriceRule("base", PriceRuleType.FIXED_BASE, amount=1000)),
            PlanSelection(
                TrafficAmount(20), DurationDays(30), DeviceLimit(2), "premium", "standard"
            ),
            OperationType.NEW_PURCHASE,
            datetime.now(UTC),
        )
    with pytest.raises(CatalogError):
        validate_tiers((PricingTier(0, 10, 1, 1), PricingTier(5, 20, 2, 2)))


def test_operation_specific_addon_rules() -> None:
    rules = price_list(
        PriceRule(
            "base", PriceRuleType.FIXED_BASE, amount=1000, operation=OperationType.TRAFFIC_ADDON
        ),
        PriceRule(
            "extension",
            PriceRuleType.FIXED_BASE,
            amount=2000,
            operation=OperationType.DURATION_EXTENSION,
        ),
    )
    assert (
        PricingEngine()
        .quote(version(), rules, selection(), OperationType.TRAFFIC_ADDON, datetime.now(UTC))
        .final.amount
        == 1000
    )
    assert (
        PricingEngine()
        .quote(version(), rules, selection(), OperationType.DURATION_EXTENSION, datetime.now(UTC))
        .final.amount
        == 2000
    )
