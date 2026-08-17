# pyright: reportPrivateUsage=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Native Telegram purchase option picker backed by authoritative catalog pricing."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .catalog import QuoteRequest, _localized, _price_preview, create_quote
from .catalog_models import ProductModel, ProductVersionModel, QuoteIdempotencyRecordModel
from .config import Settings, get_settings
from .order_models import OrderModel
from .orders import CheckoutRequest, confirm_checkout, create_checkout
from .telegram_internal import (
    Database,
    InternalAuth,
    NativePurchaseRequest,
    _committed_anchor_order,
    _customer_id,
    _native_order_result,
    _no_store,
    _option_label,
    _plan_reference,
    _product_for_plan_reference,
    _purchase_anchor,
    _purchase_idempotency_key,
    _review_revision,
)

router = APIRouter(
    prefix="/api/v1/internal/telegram/purchase-native",
    tags=["internal-telegram"],
    include_in_schema=False,
)

_GIB = 1024**3
_MAX_TRAFFIC_GB = 1_000_000
_MAX_DURATION_DAYS = 36_500
_MAX_DEVICE_COUNT = 10_000


class NativeSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    traffic_gb: int = Field(gt=0, le=_MAX_TRAFFIC_GB)
    duration_days: int = Field(gt=0, le=_MAX_DURATION_DAYS)
    device_count: int = Field(gt=0, le=_MAX_DEVICE_COUNT)
    location_code: str = Field(min_length=1, max_length=80)
    quality_code: str = Field(min_length=1, max_length=80)


class ReviewedSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    traffic_bytes: int = Field(gt=0, le=_MAX_TRAFFIC_GB * _GIB)
    duration_days: int = Field(gt=0, le=_MAX_DURATION_DAYS)
    device_count: int = Field(gt=0, le=_MAX_DEVICE_COUNT)
    location_code: str = Field(min_length=1, max_length=80)
    quality_code: str = Field(min_length=1, max_length=80)


def _version(db: Database, product: ProductModel) -> ProductVersionModel:
    version = db.get(ProductVersionModel, product.current_version_id)
    if version is None or version.status != "PUBLISHED":
        raise HTTPException(status_code=404, detail="plan_unavailable")
    return version


def _gb(value: object) -> int:
    raw = int(str(value))
    if raw <= 0 or raw % _GIB:
        raise HTTPException(status_code=409, detail="telegram_traffic_unit_unsupported")
    return raw // _GIB


def _suggestions(minimum: int, maximum: int, step: int, raw: object) -> list[int]:
    values: list[int] = []
    if isinstance(raw, list):
        for item in cast(list[object], raw):
            try:
                value = int(str(item))
            except ValueError:
                continue
            if minimum <= value <= maximum and (value - minimum) % step == 0:
                values.append(value)
    values.extend([minimum, maximum])
    if minimum < maximum:
        values.extend(
            [
                minimum + step,
                minimum + (maximum - minimum) // 2,
                maximum - step,
            ]
        )
    result: list[int] = []
    for value in sorted(set(values)):
        if minimum <= value <= maximum and (value - minimum) % step == 0:
            result.append(value)
    return result[:8]


def _numeric_range(
    options: dict[str, Any], key: str, fixed_key: str, *, traffic: bool = False
) -> dict[str, object]:
    raw_range = cast(dict[str, Any], options.get(key) or {})
    fixed = options.get(fixed_key)
    if fixed is not None:
        value = _gb(fixed) if traffic else int(str(fixed))
        return {"minimum": value, "maximum": value, "step": 1, "suggested": [value]}

    try:
        raw_minimum = int(str(raw_range["minimum"]))
        raw_maximum = int(str(raw_range["maximum"]))
        raw_step = int(str(raw_range["step"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="plan_options_unavailable") from exc
    if raw_minimum <= 0 or raw_maximum < raw_minimum or raw_step <= 0:
        raise HTTPException(status_code=409, detail="plan_options_unavailable")

    if traffic:
        minimum, maximum, step = _gb(raw_minimum), _gb(raw_maximum), _gb(raw_step)
        recommended_raw = raw_range.get("recommended", [])
        recommended: list[int] = []
        if isinstance(recommended_raw, list):
            for item in cast(list[object], recommended_raw):
                try:
                    recommended.append(_gb(item))
                except HTTPException:
                    continue
    else:
        minimum, maximum, step = raw_minimum, raw_maximum, raw_step
        recommended = []
        recommended_raw = raw_range.get("recommended", [])
        if isinstance(recommended_raw, list):
            for item in cast(list[object], recommended_raw):
                try:
                    recommended.append(int(str(item)))
                except ValueError:
                    continue
    return {
        "minimum": minimum,
        "maximum": maximum,
        "step": step,
        "suggested": _suggestions(minimum, maximum, step, recommended),
    }


def _choices(options: dict[str, Any], key: str) -> list[dict[str, str]]:
    raw = options.get(key, [])
    if not isinstance(raw, list):
        raise HTTPException(status_code=409, detail="plan_options_unavailable")
    choices: list[dict[str, str]] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            continue
        value = cast(dict[str, Any], item)
        if not value.get("enabled", True):
            continue
        code = str(value.get("code") or "")
        if not code or len(code) > 80:
            continue
        choices.append({"code": code, "label": _option_label(value)})
    if not choices:
        raise HTTPException(status_code=409, detail="plan_options_unavailable")
    return choices


def _options(db: Database, product: ProductModel, request: Request) -> dict[str, object]:
    version = _version(db, product)
    options = cast(dict[str, Any], version.options_snapshot)
    traffic = _numeric_range(options, "traffic", "fixed_traffic_bytes", traffic=True)
    duration = _numeric_range(options, "duration_days", "fixed_duration_days")
    devices = _numeric_range(options, "devices", "fixed_device_count")
    locations = _choices(options, "location_options")
    qualities = _choices(options, "quality_options")
    localized = _localized(product.localizations, "fa")
    fixed = (
        traffic["minimum"] == traffic["maximum"]
        and duration["minimum"] == duration["maximum"]
        and devices["minimum"] == devices["maximum"]
        and len(locations) == 1
        and len(qualities) == 1
    )
    price_toman: int | None = None
    if fixed:
        preview = _plan_for_selection(
            db,
            product,
            request,
            NativeSelectionRequest(
                traffic_gb=cast(int, traffic["minimum"]),
                duration_days=cast(int, duration["minimum"]),
                device_count=cast(int, devices["minimum"]),
                location_code=locations[0]["code"],
                quality_code=qualities[0]["code"],
            ),
        )
        price_toman = cast(int, preview["price_toman"])
    return {
        "reference": _plan_reference(product.machine_code),
        "title": str(localized.get("title") or localized.get("name") or "سرویس"),
        "configurable": not fixed,
        "price_toman": price_toman,
        "traffic_gb": traffic,
        "duration_days": duration,
        "devices": devices,
        "locations": locations,
        "qualities": qualities,
    }


def _plan_for_selection(
    db: Database,
    product: ProductModel,
    request: Request,
    selection: NativeSelectionRequest,
) -> dict[str, object]:
    version = _version(db, product)
    options = cast(dict[str, Any], version.options_snapshot)
    locations = _choices(options, "location_options")
    qualities = _choices(options, "quality_options")
    location = next((item for item in locations if item["code"] == selection.location_code), None)
    quality = next((item for item in qualities if item["code"] == selection.quality_code), None)
    if location is None or quality is None:
        raise HTTPException(status_code=422, detail="invalid_selection")
    quote_body = QuoteRequest(
        product_id=product.id,
        traffic_bytes=selection.traffic_gb * _GIB,
        duration_days=selection.duration_days,
        device_count=selection.device_count,
        location_code=selection.location_code,
        quality_code=selection.quality_code,
    )
    preview = _price_preview(quote_body, request, db, datetime.now(UTC))
    amount_rial = int(str(preview["final_amount_minor"]))
    if amount_rial <= 0 or amount_rial % 10:
        raise HTTPException(status_code=503, detail="price_precision_unavailable")
    localized = _localized(product.localizations, "fa")
    canonical = quote_body.model_dump(mode="json", exclude={"product_id", "operation"})
    return {
        "reference": _plan_reference(product.machine_code),
        "title": str(localized.get("title") or localized.get("name") or "سرویس"),
        "traffic_gb": selection.traffic_gb,
        "traffic_bytes": selection.traffic_gb * _GIB,
        "duration_days": selection.duration_days,
        "device_limit": selection.device_count,
        "location_code": selection.location_code,
        "location_label": location["label"],
        "quality_code": selection.quality_code,
        "quality_label": quality["label"],
        "price_toman": amount_rial // 10,
        "selection": canonical,
    }


def _product(db: Database, reference: str) -> ProductModel:
    product = _product_for_plan_reference(db, reference)
    if (
        product is None
        or product.status != "ACTIVE"
        or not product.customer_visible
        or not product.current_version_id
    ):
        raise HTTPException(status_code=404, detail="plan_unavailable")
    return product


@router.get("/catalog")
def catalog(
    request: Request,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    _customer_id(db, x_telegram_subject)
    products = db.scalars(
        select(ProductModel)
        .where(
            ProductModel.status == "ACTIVE",
            ProductModel.customer_visible.is_(True),
            ProductModel.current_version_id.is_not(None),
        )
        .order_by(ProductModel.display_order)
    ).all()
    items: list[dict[str, object]] = []
    for product in products:
        try:
            details = _options(db, product, request)
        except HTTPException as exc:
            if exc.status_code in {404, 409, 422}:
                continue
            raise
        items.append(
            {
                "reference": details["reference"],
                "title": details["title"],
                "configurable": details["configurable"],
                "price_toman": details["price_toman"],
            }
        )
    _no_store(response)
    return {"items": items}


@router.get("/plans/{plan_reference}")
def options(
    plan_reference: str,
    request: Request,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    _customer_id(db, x_telegram_subject)
    result = _options(db, _product(db, plan_reference), request)
    _no_store(response)
    return result


@router.post("/plans/{plan_reference}/preview")
def preview(
    plan_reference: str,
    body: NativeSelectionRequest,
    request: Request,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    _customer_id(db, x_telegram_subject)
    result = _plan_for_selection(db, _product(db, plan_reference), request, body)
    _no_store(response)
    return result


def _review_required(plan: dict[str, object]) -> dict[str, object]:
    return {
        "outcome": "RECONFIRM_REQUIRED",
        "order_reference": None,
        "status": "REVIEW_REQUIRED",
        "fulfillment_status": "NOT_STARTED",
        "purchase_state": "REVIEW_REQUIRED",
        "plan": plan,
        "service_reference": None,
        "service_lifecycle": None,
        "delivery_ready": False,
        "expires_at": None,
        "refunded": False,
    }


@router.post("/confirm")
def confirm(
    body: NativePurchaseRequest,
    request: Request,
    response: Response,
    _: InternalAuth,
    db: Database,
    settings: Annotated[Settings, Depends(get_settings)],
    x_telegram_subject: Annotated[int, Header(gt=0)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=120)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    anchor = _purchase_anchor(db, customer_id, idempotency_key)
    committed_order = _committed_anchor_order(db, anchor)
    if committed_order is not None:
        _no_store(response)
        return _native_order_result(db, committed_order)

    quote_key = _purchase_idempotency_key(idempotency_key, "quote", _review_revision(body))
    existing_idem = db.scalar(
        select(QuoteIdempotencyRecordModel).where(
            QuoteIdempotencyRecordModel.customer_id == customer_id,
            QuoteIdempotencyRecordModel.key_hash
            == hashlib.sha256(f"{customer_id}:{quote_key}".encode()).hexdigest(),
        )
    )
    if existing_idem and existing_idem.quote_id:
        existing_order = db.scalar(
            select(OrderModel).where(OrderModel.quote_id == existing_idem.quote_id)
        )
        if existing_order is not None:
            anchor.status = "COMMITTED"
            anchor.order_id = existing_order.id
            anchor.committed_at = datetime.now(UTC)
            _no_store(response)
            return _native_order_result(db, existing_order)

    try:
        reviewed = ReviewedSelection.model_validate(body.reviewed_selection)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_selection"
        ) from exc
    if reviewed.traffic_bytes % _GIB:
        raise HTTPException(status_code=422, detail="telegram_traffic_unit_unsupported")
    product = _product(db, body.plan_reference)
    native_selection = NativeSelectionRequest(
        traffic_gb=reviewed.traffic_bytes // _GIB,
        duration_days=reviewed.duration_days,
        device_count=reviewed.device_count,
        location_code=reviewed.location_code,
        quality_code=reviewed.quality_code,
    )
    plan = _plan_for_selection(db, product, request, native_selection)
    current_selection = cast(dict[str, int | str], plan["selection"])
    if (
        body.reviewed_price_toman != plan["price_toman"]
        or body.reviewed_selection != current_selection
    ):
        _no_store(response)
        return _review_required(plan)

    quote_body = QuoteRequest(
        product_id=product.id,
        traffic_bytes=reviewed.traffic_bytes,
        duration_days=reviewed.duration_days,
        device_count=reviewed.device_count,
        location_code=reviewed.location_code,
        quality_code=reviewed.quality_code,
    )
    session = cast(Any, SimpleNamespace(user_id=customer_id))
    quote = create_quote(quote_body, request, db, settings, session, quote_key)
    quoted_rial = int(str(quote["final_amount_minor"]))
    if quoted_rial <= 0 or quoted_rial % 10:
        raise HTTPException(status_code=503, detail="price_precision_unavailable")
    if quoted_rial // 10 != body.reviewed_price_toman:
        refreshed = {**plan, "price_toman": quoted_rial // 10}
        _no_store(response)
        return _review_required(refreshed)

    checkout = create_checkout(
        CheckoutRequest(quote_reference=str(quote["quote_reference"]), payment_method="WALLET"),
        customer_id,
        db,
        request,
        _purchase_idempotency_key(idempotency_key, "checkout"),
    )
    confirmed = confirm_checkout(
        str(cast(dict[str, Any], checkout["checkout"])["checkout_reference"]),
        customer_id,
        db,
        request,
    )
    order = cast(dict[str, Any], confirmed["order"])
    order_row = db.scalar(select(OrderModel).where(OrderModel.reference == order["order_reference"]))
    if order_row is None:
        raise HTTPException(status_code=409, detail="purchase_reconciliation_unavailable")
    order_row.snapshot = {
        **order_row.snapshot,
        "telegram_purchase_display": {
            "reference": plan["reference"],
            "title": plan["title"],
            "traffic_gb": plan["traffic_gb"],
            "duration_days": plan["duration_days"],
            "device_limit": plan["device_limit"],
            "location_label": plan["location_label"],
            "location_code": plan["location_code"],
            "quality_code": plan["quality_code"],
            "quality_label": plan["quality_label"],
            "price_toman": plan["price_toman"],
            "selection": plan["selection"],
        },
    }
    anchor.status = "COMMITTED"
    anchor.order_id = order_row.id
    anchor.committed_at = datetime.now(UTC)
    _no_store(response)
    return {
        "outcome": "ACCEPTED",
        "order_reference": order["order_reference"],
        "status": "ACCEPTED",
        "fulfillment_status": "PROVISIONING",
        "purchase_state": "PROVISIONING",
        "plan": plan,
        "service_reference": None,
        "service_lifecycle": None,
        "delivery_ready": False,
        "expires_at": None,
        "refunded": False,
    }
