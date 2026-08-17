"""Authoritative Telegram-native purchase option adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from telegram_bot.internal_api import (
    AuthoritativePrivateApiError,
    PrivateApiUnavailable,
    PurchaseOutcomeUnknown,
)
from telegram_bot.portal import CustomerContext, PurchasePlan, PurchaseResult
from telegram_bot.support_api import SupportPrivatePlatformClient


@dataclass(frozen=True)
class NativePurchaseCatalogItem:
    reference: str
    title: str
    configurable: bool
    price_toman: int | None


@dataclass(frozen=True)
class NativePurchaseRange:
    minimum: int
    maximum: int
    step: int
    suggested: tuple[int, ...]

    def accepts(self, value: int) -> bool:
        return (
            self.minimum <= value <= self.maximum
            and self.step > 0
            and (value - self.minimum) % self.step == 0
        )


@dataclass(frozen=True)
class NativePurchaseChoice:
    code: str
    label: str


@dataclass(frozen=True)
class NativePurchaseOptions:
    reference: str
    title: str
    configurable: bool
    price_toman: int | None
    traffic_gb: NativePurchaseRange
    duration_days: NativePurchaseRange
    devices: NativePurchaseRange
    locations: tuple[NativePurchaseChoice, ...]
    qualities: tuple[NativePurchaseChoice, ...]

    def fixed_selection(self) -> dict[str, int | str] | None:
        if self.configurable:
            return None
        if len(self.locations) != 1 or len(self.qualities) != 1:
            return None
        return {
            "traffic_gb": self.traffic_gb.minimum,
            "duration_days": self.duration_days.minimum,
            "device_count": self.devices.minimum,
            "location_code": self.locations[0].code,
            "quality_code": self.qualities[0].code,
        }


class NativePurchasePortal(Protocol):
    def native_purchase_catalog(
        self, context: CustomerContext
    ) -> list[NativePurchaseCatalogItem]: ...
    def native_purchase_options(
        self, context: CustomerContext, reference: str
    ) -> NativePurchaseOptions | None: ...
    def native_purchase_preview(
        self,
        context: CustomerContext,
        reference: str,
        selection: dict[str, int | str],
    ) -> PurchasePlan: ...


class NativePurchasePrivatePlatformClient(SupportPrivatePlatformClient, NativePurchasePortal):
    @staticmethod
    def _range(value: object) -> NativePurchaseRange:
        if not isinstance(value, dict):
            raise PrivateApiUnavailable("گزینه‌های خرید قابل استفاده نیست.")
        data = cast(dict[str, Any], value)
        try:
            minimum = int(data["minimum"])
            maximum = int(data["maximum"])
            step = int(data["step"])
            raw_suggested = data.get("suggested", [])
        except (KeyError, TypeError, ValueError) as exc:
            raise PrivateApiUnavailable("گزینه‌های خرید قابل استفاده نیست.") from exc
        if minimum <= 0 or maximum < minimum or step <= 0 or not isinstance(raw_suggested, list):
            raise PrivateApiUnavailable("گزینه‌های خرید قابل استفاده نیست.")
        suggested: list[int] = []
        for item in cast(list[object], raw_suggested):
            if not isinstance(item, int) or isinstance(item, bool):
                raise PrivateApiUnavailable("گزینه‌های خرید قابل استفاده نیست.")
            if minimum <= item <= maximum and (item - minimum) % step == 0:
                suggested.append(item)
        return NativePurchaseRange(minimum, maximum, step, tuple(dict.fromkeys(suggested)))

    @staticmethod
    def _choices(value: object) -> tuple[NativePurchaseChoice, ...]:
        if not isinstance(value, list):
            raise PrivateApiUnavailable("گزینه‌های خرید قابل استفاده نیست.")
        result: list[NativePurchaseChoice] = []
        for item in cast(list[object], value):
            if not isinstance(item, dict):
                raise PrivateApiUnavailable("گزینه‌های خرید قابل استفاده نیست.")
            data = cast(dict[str, Any], item)
            code, label = data.get("code"), data.get("label")
            if (
                not isinstance(code, str)
                or not code
                or len(code) > 80
                or not isinstance(label, str)
                or not label
                or len(label) > 128
            ):
                raise PrivateApiUnavailable("گزینه‌های خرید قابل استفاده نیست.")
            result.append(NativePurchaseChoice(code, label))
        if not result:
            raise PrivateApiUnavailable("گزینه‌های خرید قابل استفاده نیست.")
        return tuple(result)

    @classmethod
    def _options(cls, value: dict[str, Any]) -> NativePurchaseOptions:
        reference = value.get("reference")
        title = value.get("title")
        configurable = value.get("configurable")
        price = value.get("price_toman")
        if (
            not isinstance(reference, str)
            or not reference
            or len(reference.encode()) > 48
            or not isinstance(title, str)
            or not title
            or len(title) > 160
            or not isinstance(configurable, bool)
            or (
                price is not None
                and (not isinstance(price, int) or isinstance(price, bool) or price <= 0)
            )
        ):
            raise PrivateApiUnavailable("گزینه‌های خرید قابل استفاده نیست.")
        return NativePurchaseOptions(
            reference,
            title,
            configurable,
            price,
            cls._range(value.get("traffic_gb")),
            cls._range(value.get("duration_days")),
            cls._range(value.get("devices")),
            cls._choices(value.get("locations")),
            cls._choices(value.get("qualities")),
        )

    def native_purchase_catalog(self, context: CustomerContext) -> list[NativePurchaseCatalogItem]:
        data = self._request("GET", "/purchase-native/catalog", context.telegram_user_id)
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            raise PrivateApiUnavailable("فهرست پلن‌ها قابل استفاده نیست.")
        items = cast(list[object], raw_items)
        if len(items) > 100:
            raise PrivateApiUnavailable("فهرست پلن‌ها قابل استفاده نیست.")
        result: list[NativePurchaseCatalogItem] = []
        for item in items:
            if not isinstance(item, dict):
                raise PrivateApiUnavailable("فهرست پلن‌ها قابل استفاده نیست.")
            value = cast(dict[str, Any], item)
            reference = value.get("reference")
            title = value.get("title")
            configurable = value.get("configurable")
            price = value.get("price_toman")
            if (
                not isinstance(reference, str)
                or not reference
                or len(reference.encode()) > 48
                or not isinstance(title, str)
                or not title
                or len(title) > 160
                or not isinstance(configurable, bool)
                or (
                    price is not None
                    and (not isinstance(price, int) or isinstance(price, bool) or price <= 0)
                )
            ):
                raise PrivateApiUnavailable("فهرست پلن‌ها قابل استفاده نیست.")
            result.append(NativePurchaseCatalogItem(reference, title, configurable, price))
        return result

    def native_purchase_options(
        self, context: CustomerContext, reference: str
    ) -> NativePurchaseOptions | None:
        try:
            return self._options(
                self._request(
                    "GET",
                    f"/purchase-native/plans/{reference}",
                    context.telegram_user_id,
                )
            )
        except AuthoritativePrivateApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def native_purchase_preview(
        self,
        context: CustomerContext,
        reference: str,
        selection: dict[str, int | str],
    ) -> PurchasePlan:
        data = self._request(
            "POST",
            f"/purchase-native/plans/{reference}/preview",
            context.telegram_user_id,
            selection,
        )
        return self._purchase_plan(data)

    def confirm_purchase(
        self, context: CustomerContext, plan: PurchasePlan, idempotency_key: str
    ) -> PurchaseResult:
        body = {
            "plan_reference": plan.reference,
            "reviewed_price_toman": plan.price_toman,
            "reviewed_selection": plan.selection,
        }
        try:
            data = self._request(
                "POST",
                "/purchase-native/confirm",
                context.telegram_user_id,
                body,
                idempotency_key,
            )
        except AuthoritativePrivateApiError:
            raise
        except PrivateApiUnavailable:
            try:
                data = self._request(
                    "POST",
                    "/purchase-native/confirm",
                    context.telegram_user_id,
                    body,
                    idempotency_key,
                )
            except AuthoritativePrivateApiError:
                raise
            except PrivateApiUnavailable as exc:
                raise PurchaseOutcomeUnknown(
                    "نتیجه خرید هنوز مشخص نیست؛ با همان درخواست دوباره بررسی کنید."
                ) from exc
        return self._purchase_result(data)
