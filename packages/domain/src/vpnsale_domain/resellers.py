from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ResellerDomainError(ValueError):
    pass


class ResellerStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    TERMINATED = "TERMINATED"
    ARCHIVED = "ARCHIVED"


class ResellerTierCode(StrEnum):
    STARTER = "STARTER"
    STANDARD = "STANDARD"
    PROFESSIONAL = "PROFESSIONAL"
    ENTERPRISE = "ENTERPRISE"


class SettlementMode(StrEnum):
    PREPAID = "PREPAID"
    CONTROLLED_CREDIT = "CONTROLLED_CREDIT"


class PriceScope(StrEnum):
    PURCHASE = "PURCHASE"
    RENEWAL = "RENEWAL"
    ADD_ON = "ADD_ON"


class PricingRuleKind(StrEnum):
    EXACT = "EXACT"
    PERCENT_DISCOUNT = "PERCENT_DISCOUNT"
    FIXED_DISCOUNT = "FIXED_DISCOUNT"
    TIER_DISCOUNT = "TIER_DISCOUNT"


RESELLER_TRANSITIONS: dict[ResellerStatus, set[ResellerStatus]] = {
    ResellerStatus.DRAFT: {ResellerStatus.PENDING_REVIEW, ResellerStatus.ARCHIVED},
    ResellerStatus.PENDING_REVIEW: {
        ResellerStatus.ACTIVE,
        ResellerStatus.DRAFT,
        ResellerStatus.BLOCKED,
    },
    ResellerStatus.ACTIVE: {
        ResellerStatus.SUSPENDED,
        ResellerStatus.BLOCKED,
        ResellerStatus.TERMINATED,
    },
    ResellerStatus.SUSPENDED: {
        ResellerStatus.ACTIVE,
        ResellerStatus.BLOCKED,
        ResellerStatus.TERMINATED,
    },
    ResellerStatus.BLOCKED: {ResellerStatus.SUSPENDED, ResellerStatus.TERMINATED},
    ResellerStatus.TERMINATED: {ResellerStatus.ARCHIVED},
    ResellerStatus.ARCHIVED: set(),
}


def require_reseller_transition(current: str, target: str) -> None:
    source = ResellerStatus(current)
    destination = ResellerStatus(target)
    if destination not in RESELLER_TRANSITIONS[source]:
        raise ResellerDomainError(f"illegal reseller transition {current}->{target}")


def require_expected_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise ResellerDomainError("stale reseller version")


@dataclass(frozen=True)
class ResellerQuotaPolicy:
    max_managed_customers: int
    max_active_orders: int
    daily_purchase_amount_rial: int
    monthly_purchase_amount_rial: int
    daily_order_count: int
    monthly_order_count: int
    credit_limit_rial: int
    max_outstanding_debt_rial: int
    custom_remarks_allowed: bool

    def stricter_with(self, override: ResellerQuotaPolicy | None) -> ResellerQuotaPolicy:
        if override is None:
            return self
        return ResellerQuotaPolicy(
            max_managed_customers=min(self.max_managed_customers, override.max_managed_customers),
            max_active_orders=min(self.max_active_orders, override.max_active_orders),
            daily_purchase_amount_rial=min(
                self.daily_purchase_amount_rial, override.daily_purchase_amount_rial
            ),
            monthly_purchase_amount_rial=min(
                self.monthly_purchase_amount_rial, override.monthly_purchase_amount_rial
            ),
            daily_order_count=min(self.daily_order_count, override.daily_order_count),
            monthly_order_count=min(self.monthly_order_count, override.monthly_order_count),
            credit_limit_rial=min(self.credit_limit_rial, override.credit_limit_rial),
            max_outstanding_debt_rial=min(
                self.max_outstanding_debt_rial, override.max_outstanding_debt_rial
            ),
            custom_remarks_allowed=self.custom_remarks_allowed and override.custom_remarks_allowed,
        )


@dataclass(frozen=True)
class ResellerPricingRule:
    kind: PricingRuleKind
    priority: int
    scope: PriceScope
    exact_amount_rial: int | None = None
    percent_bps: int | None = None
    fixed_discount_rial: int | None = None
    min_quantity: int = 1
    minimum_price_rial: int = 0
    minimum_margin_rial: int = 0
    suggested_retail_rial: int | None = None


@dataclass(frozen=True)
class ResellerPriceResult:
    base_price_rial: int
    final_wholesale_rial: int
    discount_rial: int
    applied_rule_kind: str
    minimum_price_rial: int
    minimum_margin_rial: int
    explanation: tuple[str, ...]


def evaluate_reseller_price(
    base_price_rial: int, rules: list[ResellerPricingRule], quantity: int = 1
) -> ResellerPriceResult:
    if isinstance(base_price_rial, bool) or base_price_rial <= 0 or quantity <= 0:
        raise ResellerDomainError("price and quantity must be positive integer rial")
    applicable = [r for r in rules if r.min_quantity <= quantity]
    if not applicable:
        return ResellerPriceResult(
            base_price_rial, base_price_rial, 0, "BASE", 0, 0, ("base_price",)
        )
    applicable.sort(key=lambda r: (r.priority, -r.min_quantity))
    rule = applicable[0]
    if (
        sum(
            1
            for r in applicable
            if (r.priority, r.min_quantity) == (rule.priority, rule.min_quantity)
        )
        > 1
    ):
        raise ResellerDomainError("ambiguous reseller pricing rules")
    if rule.kind == PricingRuleKind.EXACT:
        candidate = rule.exact_amount_rial
        if candidate is None:
            raise ResellerDomainError("exact rule requires exact amount")
    elif rule.kind == PricingRuleKind.PERCENT_DISCOUNT:
        if rule.percent_bps is None or not 0 <= rule.percent_bps <= 10_000:
            raise ResellerDomainError("invalid percent discount")
        candidate = base_price_rial - ((base_price_rial * rule.percent_bps) // 10_000)
    elif rule.kind in {PricingRuleKind.FIXED_DISCOUNT, PricingRuleKind.TIER_DISCOUNT}:
        if rule.fixed_discount_rial is None or rule.fixed_discount_rial < 0:
            raise ResellerDomainError("invalid fixed discount")
        candidate = base_price_rial - rule.fixed_discount_rial
    else:  # pragma: no cover
        raise ResellerDomainError("unsupported reseller pricing rule")
    floor = max(rule.minimum_price_rial, rule.minimum_margin_rial)
    final = max(candidate, floor)
    if final < 0:
        raise ResellerDomainError("negative reseller price")
    return ResellerPriceResult(
        base_price_rial=base_price_rial,
        final_wholesale_rial=final,
        discount_rial=max(base_price_rial - final, 0),
        applied_rule_kind=rule.kind.value,
        minimum_price_rial=rule.minimum_price_rial,
        minimum_margin_rial=rule.minimum_margin_rial,
        explanation=(
            "base_price",
            rule.kind.value,
            "floor_enforced" if final != candidate else "floor_not_needed",
        ),
    )


_ALLOWED_PLACEHOLDERS = {
    "reseller_brand",
    "customer_label",
    "product_name",
    "location",
    "order_short_id",
    "service_short_id",
    "sequence",
}
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
_UNSAFE_RE = re.compile(r"[\x00-\x1f\x7f]|https?://|[a-zA-Z][a-zA-Z0-9+.-]*:|<|>|`|\\")
_SAFE_CHARS_RE = re.compile(r"^[\w\s\-._|()[\]/{}\u0600-\u06FF]+$")


def validate_remark_template(template: str, max_length: int = 96) -> None:
    if not template or len(template) > max_length:
        raise ResellerDomainError("remark template length invalid")
    if _UNSAFE_RE.search(template) or not _SAFE_CHARS_RE.match(template):
        raise ResellerDomainError("unsafe remark template")
    unknown = set(_PLACEHOLDER_RE.findall(template)) - _ALLOWED_PLACEHOLDERS
    if unknown:
        raise ResellerDomainError("unknown remark placeholder")


def render_remark_template(template: str, values: dict[str, str], max_length: int = 96) -> str:
    validate_remark_template(template, max_length=max_length)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key, "")
        if _UNSAFE_RE.search(value):
            raise ResellerDomainError("unsafe remark value")
        return value

    rendered = _PLACEHOLDER_RE.sub(repl, template).strip()
    if len(rendered) > max_length or not rendered:
        raise ResellerDomainError("rendered remark length invalid")
    return rendered


@dataclass(frozen=True)
class CreditFacility:
    limit_rial: int
    utilized_rial: int
    blocked: bool
    effective_at: datetime
    expires_at: datetime | None = None

    def reserve(self, amount_rial: int) -> CreditFacility:
        if self.blocked or amount_rial <= 0 or self.utilized_rial + amount_rial > self.limit_rial:
            raise ResellerDomainError("credit limit exceeded")
        return CreditFacility(
            self.limit_rial,
            self.utilized_rial + amount_rial,
            self.blocked,
            self.effective_at,
            self.expires_at,
        )
