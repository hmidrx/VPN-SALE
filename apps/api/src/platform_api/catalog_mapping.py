# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.catalog import (
    CatalogOption,
    FulfillmentRequirement,
    LocalizedText,
    OperationType,
    PlanConstraint,
    PlanOptions,
    PriceListVersion,
    PriceRule,
    PriceRuleType,
    PricingTier,
    ProductType,
    ProductVersion,
    ProductVersionStatus,
    RangeConstraint,
)

from platform_api.catalog_models import (
    PriceListVersionModel,
    PricingRuleModel,
    PricingTierModel,
    ProductVersionModel,
)


def _labels(items: list[dict[str, str]] | dict[str, str]) -> tuple[LocalizedText, ...]:
    if isinstance(items, dict):
        return tuple(LocalizedText(k, v) for k, v in items.items())
    return tuple(LocalizedText(i["locale"], i["value"]) for i in items)


def _option(raw: dict[str, object]) -> CatalogOption:
    return CatalogOption(
        str(raw["code"]),
        _labels(raw.get("labels", {"fa": str(raw["code"])})),
        bool(raw.get("enabled", True)),
    )


def _range(raw: dict[str, object]) -> RangeConstraint:
    return RangeConstraint(
        int(raw["minimum"]),
        int(raw["maximum"]),
        int(raw["step"]),
        tuple(int(x) for x in raw.get("recommended", ())),
        bool(raw.get("allow_unlimited", False)),
    )


def domain_product_version(model: ProductVersionModel) -> ProductVersion:
    options = cast(dict[str, Any], model.options_snapshot)
    plan = PlanOptions(
        traffic=_range(options["traffic"]),
        duration_days=_range(options["duration_days"]),
        devices=_range(options["devices"]),
        location_options=tuple(_option(x) for x in options["location_options"]),
        quality_options=tuple(_option(x) for x in options["quality_options"]),
        fixed_traffic_bytes=options.get("fixed_traffic_bytes"),
        fixed_duration_days=options.get("fixed_duration_days"),
        fixed_device_count=options.get("fixed_device_count"),
    )
    constraints = tuple(
        PlanConstraint(
            str(c["kind"]),
            str(c["selector_code"]),
            c.get("minimum_duration_days"),
            c.get("maximum_device_count"),
        )
        for c in model.constraints_snapshot
        if isinstance(c, dict)
    )
    fulfillment = tuple(
        FulfillmentRequirement(
            str(f["capability_code"]),
            int(f.get("minimum_version", 1)),
            bool(f.get("required", True)),
        )
        for f in model.fulfillment_requirements_snapshot
        if isinstance(f, dict)
    )
    return ProductVersion(
        id=UUID(str(model.id)),
        product_id=UUID(str(model.product_id)),
        version_number=model.version_number,
        status=ProductVersionStatus(model.status),
        product_type=ProductType(model.product_type),
        options=plan,
        constraints=constraints,
        fulfillment=fulfillment,
        published_at=model.published_at,
    )


def domain_price_list(db: Session, model: PriceListVersionModel) -> PriceListVersion:
    rules: list[PriceRule] = []
    for r in db.execute(
        select(PricingRuleModel)
        .where(PricingRuleModel.price_list_version_id == model.id)
        .order_by(PricingRuleModel.priority)
    ).scalars():
        tiers = tuple(
            PricingTier(t.lower_inclusive, t.upper_exclusive, t.unit_amount_minor, t.priority)
            for t in db.execute(
                select(PricingTierModel)
                .where(PricingTierModel.pricing_rule_id == r.id)
                .order_by(PricingTierModel.priority)
            ).scalars()
        )
        rules.append(
            PriceRule(
                code=r.code,
                rule_type=PriceRuleType(r.rule_type),
                amount=r.amount_minor,
                unit_size=r.unit_size,
                percentage_basis_points=r.percentage_basis_points,
                priority=r.priority,
                operation=OperationType(r.operation) if r.operation else None,
                selector_code=r.selector_code,
                tiers=tiers,
            )
        )
    return PriceListVersion(
        UUID(str(model.id)),
        UUID(str(model.price_list_id)),
        model.version_number,
        model.currency,
        model.active_from,
        model.active_until,
        model.priority,
        model.active,
        model.segment_key,
        tuple(rules),
    )
