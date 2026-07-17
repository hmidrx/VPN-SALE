from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

MAX_MONEY_MINOR = 9_000_000_000_000_000
MAX_TRAFFIC_BYTES = 10 * 1024**5
MAX_DURATION_DAYS = 3650
MAX_DEVICE_COUNT = 10_000
CATALOG_PRICING_ENGINE_VERSION = "catalog-pricing-v1"
MACHINE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,78}$")
LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
FULFILLMENT_CAPABILITIES = frozenset(
    {
        "protocol.vless",
        "protocol.vmess",
        "protocol.trojan",
        "delivery.subscription_link",
        "delivery.single_config",
        "delivery.qr",
        "limit.traffic",
        "limit.expiry",
        "limit.devices",
        "location.group",
        "quality.tier",
    }
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class CatalogError(ValueError):
    pass


class InvalidCatalogTransition(CatalogError):
    pass


class CategoryStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProductStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"
    ARCHIVED = "ARCHIVED"


class ProductVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ProductType(StrEnum):
    FIXED_PLAN = "FIXED_PLAN"
    CUSTOM_PLAN = "CUSTOM_PLAN"


class OperationType(StrEnum):
    NEW_PURCHASE = "NEW_PURCHASE"
    RENEWAL = "RENEWAL"
    TRAFFIC_ADDON = "TRAFFIC_ADDON"
    DURATION_EXTENSION = "DURATION_EXTENSION"


class PriceRuleType(StrEnum):
    FIXED_BASE = "FIXED_BASE"
    PER_TRAFFIC_UNIT = "PER_TRAFFIC_UNIT"
    PER_DURATION_UNIT = "PER_DURATION_UNIT"
    PER_DEVICE = "PER_DEVICE"
    LOCATION_SURCHARGE = "LOCATION_SURCHARGE"
    QUALITY_SURCHARGE = "QUALITY_SURCHARGE"
    FIXED_ADJUSTMENT = "FIXED_ADJUSTMENT"
    PERCENTAGE_ADJUSTMENT = "PERCENTAGE_ADJUSTMENT"
    MINIMUM_FINAL = "MINIMUM_FINAL"
    MAXIMUM_FINAL = "MAXIMUM_FINAL"
    VOLUME_TIER = "VOLUME_TIER"
    DURATION_TIER = "DURATION_TIER"


class QuoteStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    CONSUMED_RESERVED_FOR_FUTURE = "CONSUMED_RESERVED_FOR_FUTURE"


CATEGORY_TRANSITIONS: dict[CategoryStatus, frozenset[CategoryStatus]] = {
    CategoryStatus.DRAFT: frozenset({CategoryStatus.ACTIVE, CategoryStatus.ARCHIVED}),
    CategoryStatus.ACTIVE: frozenset({CategoryStatus.ARCHIVED}),
    CategoryStatus.ARCHIVED: frozenset(),
}
PRODUCT_TRANSITIONS: dict[ProductStatus, frozenset[ProductStatus]] = {
    ProductStatus.DRAFT: frozenset({ProductStatus.ACTIVE, ProductStatus.ARCHIVED}),
    ProductStatus.ACTIVE: frozenset({ProductStatus.PAUSED, ProductStatus.RETIRED}),
    ProductStatus.PAUSED: frozenset({ProductStatus.ACTIVE, ProductStatus.RETIRED}),
    ProductStatus.RETIRED: frozenset({ProductStatus.ARCHIVED}),
    ProductStatus.ARCHIVED: frozenset(),
}
VERSION_TRANSITIONS: dict[ProductVersionStatus, frozenset[ProductVersionStatus]] = {
    ProductVersionStatus.DRAFT: frozenset(
        {ProductVersionStatus.PUBLISHED, ProductVersionStatus.RETIRED}
    ),
    ProductVersionStatus.PUBLISHED: frozenset(
        {ProductVersionStatus.SUPERSEDED, ProductVersionStatus.RETIRED}
    ),
    ProductVersionStatus.SUPERSEDED: frozenset({ProductVersionStatus.RETIRED}),
    ProductVersionStatus.RETIRED: frozenset(),
}


def ensure_transition(current: StrEnum, target: StrEnum) -> None:
    if isinstance(current, CategoryStatus) and isinstance(target, CategoryStatus):
        allowed = CATEGORY_TRANSITIONS[current]
    elif isinstance(current, ProductStatus) and isinstance(target, ProductStatus):
        allowed = PRODUCT_TRANSITIONS[current]
    elif isinstance(current, ProductVersionStatus) and isinstance(target, ProductVersionStatus):
        allowed = VERSION_TRANSITIONS[current]
    else:
        raise InvalidCatalogTransition(f"illegal transition: {current} -> {target}")
    if current != target and target not in allowed:
        raise InvalidCatalogTransition(f"illegal transition: {current} -> {target}")


def machine_code(value: str) -> str:
    code = value.strip().casefold()
    if not MACHINE_CODE_RE.fullmatch(code):
        raise CatalogError("machine code must be a stable snake_case identifier")
    return code


@dataclass(frozen=True, slots=True)
class Money:
    amount: int
    currency: str = "IRR"

    def __post_init__(self) -> None:
        if self.amount < 0 or self.amount > MAX_MONEY_MINOR:
            raise CatalogError("money amount out of bounds")
        if not re.fullmatch(r"[A-Z]{3,8}", self.currency):
            raise CatalogError("invalid currency")

    def add(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise CatalogError("currency mismatch")
        return Money(self.amount + other.amount, self.currency)

    def multiply_ratio(self, numerator: int, denominator: int = 1) -> Money:
        if denominator <= 0 or numerator < 0:
            raise CatalogError("invalid multiplier")
        return Money((self.amount * numerator + denominator - 1) // denominator, self.currency)

    def to_toman(self) -> int:
        if self.currency != "IRR":
            raise CatalogError("toman display is defined only for IRR")
        return self.amount // 10


@dataclass(frozen=True, slots=True)
class TrafficAmount:
    bytes: int
    unlimited: bool = False

    def __post_init__(self) -> None:
        if self.unlimited:
            if self.bytes != 0:
                raise CatalogError("unlimited traffic must not carry byte amount")
        elif self.bytes <= 0 or self.bytes > MAX_TRAFFIC_BYTES:
            raise CatalogError("traffic bytes out of bounds")

    @classmethod
    def gib(cls, value: int) -> TrafficAmount:
        return cls(value * 1024**3)


@dataclass(frozen=True, slots=True)
class DurationDays:
    days: int

    def __post_init__(self) -> None:
        if self.days <= 0 or self.days > MAX_DURATION_DAYS:
            raise CatalogError("duration days out of bounds")


@dataclass(frozen=True, slots=True)
class DeviceLimit:
    count: int
    unlimited: bool = False

    def __post_init__(self) -> None:
        if self.unlimited:
            if self.count != 0:
                raise CatalogError("unlimited devices must not carry count")
        elif self.count <= 0 or self.count > MAX_DEVICE_COUNT:
            raise CatalogError("device count out of bounds")


@dataclass(frozen=True, slots=True)
class RangeConstraint:
    minimum: int
    maximum: int
    step: int
    recommended: tuple[int, ...] = ()
    allow_unlimited: bool = False

    def validate(self, value: int, field_name: str) -> None:
        if value < self.minimum or value > self.maximum or (value - self.minimum) % self.step:
            raise CatalogError(f"invalid {field_name}")

    def __post_init__(self) -> None:
        if self.minimum <= 0 or self.maximum < self.minimum or self.step <= 0:
            raise CatalogError("invalid range constraint")
        for value in self.recommended:
            self.validate(value, "recommended value")


@dataclass(frozen=True, slots=True)
class LocalizedText:
    locale: str
    value: str

    def __post_init__(self) -> None:
        if not LOCALE_RE.fullmatch(self.locale):
            raise CatalogError("invalid locale")
        if (
            not self.value.strip()
            or len(self.value) > 2000
            or "<" in self.value
            or ">" in self.value
        ):
            raise CatalogError("invalid localized text")


@dataclass(frozen=True, slots=True)
class CatalogOption:
    code: str
    labels: tuple[LocalizedText, ...]
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", machine_code(self.code))
        if not self.labels:
            raise CatalogError("option requires labels")


@dataclass(frozen=True, slots=True)
class PlanOptions:
    traffic: RangeConstraint
    duration_days: RangeConstraint
    devices: RangeConstraint
    location_options: tuple[CatalogOption, ...]
    quality_options: tuple[CatalogOption, ...]
    fixed_traffic_bytes: int | None = None
    fixed_duration_days: int | None = None
    fixed_device_count: int | None = None

    def validate_selection(self, selection: PlanSelection, product_type: ProductType) -> None:
        if product_type == ProductType.FIXED_PLAN:
            if (
                selection.traffic.bytes != self.fixed_traffic_bytes
                or selection.duration.days != self.fixed_duration_days
                or selection.devices.count != self.fixed_device_count
            ):
                raise CatalogError("fixed plan selection does not match template")
        self.traffic.validate(selection.traffic.bytes, "traffic_bytes")
        self.duration_days.validate(selection.duration.days, "duration_days")
        self.devices.validate(selection.devices.count, "device_count")
        if selection.location_code not in {o.code for o in self.location_options if o.enabled}:
            raise CatalogError("invalid location_code")
        if selection.quality_code not in {o.code for o in self.quality_options if o.enabled}:
            raise CatalogError("invalid quality_code")


@dataclass(frozen=True, slots=True)
class PlanSelection:
    traffic: TrafficAmount
    duration: DurationDays
    devices: DeviceLimit
    location_code: str
    quality_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "location_code", machine_code(self.location_code))
        object.__setattr__(self, "quality_code", machine_code(self.quality_code))

    def fingerprint(self) -> dict[str, object]:
        return {
            "traffic_bytes": self.traffic.bytes,
            "duration_days": self.duration.days,
            "device_count": self.devices.count,
            "location_code": self.location_code,
            "quality_code": self.quality_code,
        }


@dataclass(frozen=True, slots=True)
class PlanConstraint:
    kind: str
    selector_code: str
    minimum_duration_days: int | None = None
    maximum_device_count: int | None = None

    def validate(self, selection: PlanSelection) -> None:
        if self.kind == "LOCATION_MIN_DURATION":
            if (
                selection.location_code == self.selector_code
                and self.minimum_duration_days
                and selection.duration.days < self.minimum_duration_days
            ):
                raise CatalogError("location requires longer duration")
            return
        if self.kind == "QUALITY_MAX_DEVICES":
            if (
                selection.quality_code == self.selector_code
                and self.maximum_device_count
                and selection.devices.count > self.maximum_device_count
            ):
                raise CatalogError("quality tier does not allow device count")
            return
        raise CatalogError("unsupported plan constraint")


@dataclass(frozen=True, slots=True)
class FulfillmentRequirement:
    capability_code: str
    minimum_version: int = 1
    required: bool = True

    def __post_init__(self) -> None:
        if self.capability_code not in FULFILLMENT_CAPABILITIES:
            raise CatalogError("unknown fulfillment capability")
        if self.minimum_version <= 0:
            raise CatalogError("invalid capability version")


@dataclass(frozen=True, slots=True)
class PricingTier:
    lower_inclusive: int
    upper_exclusive: int | None
    unit_amount: int
    priority: int

    def __post_init__(self) -> None:
        if self.lower_inclusive < 0 or (
            self.upper_exclusive is not None and self.upper_exclusive <= self.lower_inclusive
        ):
            raise CatalogError("invalid tier bounds")
        Money(self.unit_amount)


def validate_tiers(tiers: tuple[PricingTier, ...], *, continuous: bool = True) -> None:
    seen: set[int] = set()
    expected = 0
    for tier in sorted(tiers, key=lambda t: (t.lower_inclusive, t.priority)):
        if tier.priority in seen:
            raise CatalogError("duplicate tier priority")
        seen.add(tier.priority)
        if continuous and tier.lower_inclusive != expected:
            raise CatalogError("tier gap")
        expected = tier.upper_exclusive if tier.upper_exclusive is not None else expected
    for left, right in zip(
        sorted(tiers, key=lambda t: t.lower_inclusive),
        sorted(tiers, key=lambda t: t.lower_inclusive)[1:],
        strict=False,
    ):
        if left.upper_exclusive is None or left.upper_exclusive > right.lower_inclusive:
            raise CatalogError("overlapping tiers")


@dataclass(frozen=True, slots=True)
class PriceRule:
    code: str
    rule_type: PriceRuleType
    amount: int = 0
    unit_size: int = 1
    percentage_basis_points: int = 0
    priority: int = 100
    operation: OperationType | None = None
    selector_code: str | None = None
    tiers: tuple[PricingTier, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", machine_code(self.code))
        if self.unit_size <= 0 or self.priority < 0:
            raise CatalogError("invalid price rule")
        Money(abs(self.amount))
        if self.percentage_basis_points < -10_000 or self.percentage_basis_points > 100_000:
            raise CatalogError("invalid percentage adjustment")
        validate_tiers(self.tiers, continuous=False) if self.tiers else None


@dataclass(frozen=True, slots=True)
class PriceListVersion:
    id: UUID
    price_list_id: UUID
    version: int
    currency: str
    active_from: datetime
    active_until: datetime | None
    priority: int
    active: bool
    segment_key: str | None = None
    rules: tuple[PriceRule, ...] = ()

    def is_active_at(self, at: datetime, segment: str | None) -> bool:
        return (
            self.active
            and self.active_from <= at
            and (self.active_until is None or at < self.active_until)
            and (self.segment_key is None or self.segment_key == segment)
        )


@dataclass(frozen=True, slots=True)
class ProductVersion:
    id: UUID
    product_id: UUID
    version_number: int
    status: ProductVersionStatus
    product_type: ProductType
    options: PlanOptions
    constraints: tuple[PlanConstraint, ...] = ()
    fulfillment: tuple[FulfillmentRequirement, ...] = ()
    published_at: datetime | None = None

    def publish(self, at: datetime | None = None) -> ProductVersion:
        ensure_transition(self.status, ProductVersionStatus.PUBLISHED)
        if not self.fulfillment:
            raise CatalogError("published product version requires fulfillment requirements")
        return ProductVersion(
            self.id,
            self.product_id,
            self.version_number,
            ProductVersionStatus.PUBLISHED,
            self.product_type,
            self.options,
            self.constraints,
            self.fulfillment,
            at or utc_now(),
        )


@dataclass(frozen=True, slots=True)
class PriceComponent:
    code: str
    label: str
    amount: Money
    order: int


@dataclass(frozen=True, slots=True)
class PricingResult:
    currency: str
    subtotal: Money
    adjustments: tuple[PriceComponent, ...]
    components: tuple[PriceComponent, ...]
    final: Money
    engine_version: str = CATALOG_PRICING_ENGINE_VERSION


RULE_ORDER = {
    PriceRuleType.FIXED_BASE: 10,
    PriceRuleType.PER_TRAFFIC_UNIT: 20,
    PriceRuleType.VOLUME_TIER: 20,
    PriceRuleType.PER_DURATION_UNIT: 30,
    PriceRuleType.DURATION_TIER: 30,
    PriceRuleType.PER_DEVICE: 40,
    PriceRuleType.LOCATION_SURCHARGE: 50,
    PriceRuleType.QUALITY_SURCHARGE: 60,
    PriceRuleType.FIXED_ADJUSTMENT: 70,
    PriceRuleType.PERCENTAGE_ADJUSTMENT: 80,
    PriceRuleType.MINIMUM_FINAL: 90,
    PriceRuleType.MAXIMUM_FINAL: 91,
}


class PricingEngine:
    def quote(
        self,
        version: ProductVersion,
        price_list: PriceListVersion,
        selection: PlanSelection,
        operation: OperationType,
        at: datetime,
    ) -> PricingResult:
        if version.status != ProductVersionStatus.PUBLISHED:
            raise CatalogError("product version is not published")
        if not price_list.is_active_at(at, price_list.segment_key):
            raise CatalogError("price list is not active")
        version.options.validate_selection(selection, version.product_type)
        for constraint in version.constraints:
            constraint.validate(selection)
        components: list[PriceComponent] = []
        total = Money(0, price_list.currency)
        for rule in sorted(
            price_list.rules, key=lambda r: (RULE_ORDER[r.rule_type], r.priority, r.code)
        ):
            if rule.operation and rule.operation != operation:
                continue
            amount = self._apply_rule(rule, selection, total, price_list.currency)
            if amount.amount == 0 and rule.rule_type not in {
                PriceRuleType.MINIMUM_FINAL,
                PriceRuleType.MAXIMUM_FINAL,
            }:
                continue
            if rule.rule_type == PriceRuleType.MINIMUM_FINAL and total.amount < amount.amount:
                amount = Money(amount.amount - total.amount, price_list.currency)
            elif rule.rule_type == PriceRuleType.MAXIMUM_FINAL and total.amount > amount.amount:
                amount = Money(0, price_list.currency)
                total = Money(rule.amount, price_list.currency)
            elif rule.rule_type == PriceRuleType.MAXIMUM_FINAL:
                continue
            total = total.add(amount)
            components.append(
                PriceComponent(
                    rule.code, rule.rule_type.value.lower(), amount, RULE_ORDER[rule.rule_type]
                )
            )
        if total.amount <= 0:
            raise CatalogError("final price must be positive")
        return PricingResult(price_list.currency, total, tuple(), tuple(components), total)

    def _apply_rule(
        self, rule: PriceRule, selection: PlanSelection, current: Money, currency: str
    ) -> Money:
        if rule.rule_type == PriceRuleType.FIXED_BASE:
            return Money(rule.amount, currency)
        if rule.rule_type == PriceRuleType.PER_TRAFFIC_UNIT:
            return Money(
                ((selection.traffic.bytes + rule.unit_size - 1) // rule.unit_size) * rule.amount,
                currency,
            )
        if rule.rule_type == PriceRuleType.PER_DURATION_UNIT:
            return Money(
                ((selection.duration.days + rule.unit_size - 1) // rule.unit_size) * rule.amount,
                currency,
            )
        if rule.rule_type == PriceRuleType.PER_DEVICE:
            return Money(selection.devices.count * rule.amount, currency)
        if rule.rule_type == PriceRuleType.LOCATION_SURCHARGE:
            return Money(
                rule.amount if rule.selector_code == selection.location_code else 0, currency
            )
        if rule.rule_type == PriceRuleType.QUALITY_SURCHARGE:
            return Money(
                rule.amount if rule.selector_code == selection.quality_code else 0, currency
            )
        if rule.rule_type == PriceRuleType.FIXED_ADJUSTMENT:
            return Money(rule.amount, currency)
        if rule.rule_type == PriceRuleType.PERCENTAGE_ADJUSTMENT:
            return current.multiply_ratio(rule.percentage_basis_points, 10_000)
        if rule.rule_type == PriceRuleType.MINIMUM_FINAL:
            return Money(rule.amount, currency)
        if rule.rule_type == PriceRuleType.MAXIMUM_FINAL:
            return Money(rule.amount, currency)
        if rule.rule_type in {PriceRuleType.VOLUME_TIER, PriceRuleType.DURATION_TIER}:
            basis = (
                selection.traffic.bytes
                if rule.rule_type == PriceRuleType.VOLUME_TIER
                else selection.duration.days
            )
            for tier in sorted(rule.tiers, key=lambda t: t.priority):
                if basis >= tier.lower_inclusive and (
                    tier.upper_exclusive is None or basis < tier.upper_exclusive
                ):
                    return Money(tier.unit_amount, currency)
        return Money(0, currency)


def request_fingerprint(payload: dict[str, Any]) -> str:
    normalized = repr(sorted(payload.items())).encode()
    return hashlib.sha256(normalized).hexdigest()


@dataclass(frozen=True, slots=True)
class CustomerPriceQuote:
    id: UUID
    reference: str
    product_id: UUID
    product_version_id: UUID
    customer_id: UUID
    operation: OperationType
    selection: PlanSelection
    price_list_version_id: UUID
    currency: str
    subtotal: Money
    components: tuple[PriceComponent, ...]
    final: Money
    issued_at: datetime
    expires_at: datetime
    status: QuoteStatus = QuoteStatus.ACTIVE
    pricing_engine_version: str = CATALOG_PRICING_ENGINE_VERSION

    @classmethod
    def issue(
        cls,
        *,
        product_id: UUID,
        product_version_id: UUID,
        customer_id: UUID,
        operation: OperationType,
        selection: PlanSelection,
        price_list_version_id: UUID,
        pricing: PricingResult,
        lifetime_seconds: int,
        at: datetime | None = None,
    ) -> CustomerPriceQuote:
        now = at or utc_now()
        return cls(
            uuid4(),
            hashlib.sha256(uuid4().bytes).hexdigest()[:32],
            product_id,
            product_version_id,
            customer_id,
            operation,
            selection,
            price_list_version_id,
            pricing.currency,
            pricing.subtotal,
            pricing.components,
            pricing.final,
            now,
            now + timedelta(seconds=lifetime_seconds),
        )

    def visible_status(self, at: datetime | None = None) -> QuoteStatus:
        return (
            QuoteStatus.EXPIRED
            if self.status == QuoteStatus.ACTIVE and self.expires_at <= (at or utc_now())
            else self.status
        )
