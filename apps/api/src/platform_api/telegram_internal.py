# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
"""Private, service-authenticated Telegram bridge (never routed by Caddy)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .catalog import QuoteRequest, _localized, _price_preview, create_quote
from .catalog_models import ProductModel, ProductVersionModel, QuoteIdempotencyRecordModel
from .config import Settings, get_settings
from .database import get_db_session
from .identity.models import CustomerProfileModel, TelegramAccountModel, UserModel
from .manual_topups import (
    CreateRequest as ManualTopupCreateRequest,
)
from .manual_topups import (
    cancel_manual_topup_for_customer,
    create_manual_topup_for_customer,
    list_manual_topups_for_customer,
    store_receipt_for_customer,
)
from .manual_topups import (
    customer_manual_topup_destination_settings as manual_topup_destination_settings,
)
from .manual_topups import (
    customer_manual_topup_dto as manual_topup_dto,
)
from .manual_topups import (
    customer_manual_topup_request as manual_topup_request,
)
from .notification_preferences import (
    NotificationPreferencePatch,
    NotificationPreferencesOut,
    get_preferences,
    patch_preferences,
)
from .order_models import OrderModel, TelegramPurchaseIdempotencyModel
from .orders import CheckoutRequest, confirm_checkout, create_checkout, order_detail
from .service_models import ServiceModel
from .services import (
    CustomerServiceSummary,
    customer_service_projection,
    customer_service_summaries,
)
from .wallet import customer_transaction_page, customer_wallet_projection

router = APIRouter(
    prefix="/api/v1/internal/telegram", tags=["internal-telegram"], include_in_schema=False
)


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_user_id: int = Field(gt=0)
    username: str | None = Field(default=None, max_length=32)
    first_name: str | None = Field(default=None, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)
    language_code: str | None = Field(default=None, max_length=16)
    bot_started: bool = True


class NativePurchaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_reference: str = Field(pattern=r"^[a-z][a-z0-9_]{1,78}$")
    reviewed_price_toman: int = Field(gt=0)
    reviewed_selection: dict[str, int | str]


def _authenticate(
    authorization: Annotated[str | None, Header()] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> None:
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    try:
        expected = Path(settings.telegram_internal_token_file).read_text().strip()
    except OSError:
        expected = ""
    if len(expected) < 32 or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="unauthenticated")


InternalAuth = Annotated[None, Depends(_authenticate)]
Database = Annotated[Session, Depends(get_db_session)]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _account(db: Session, telegram_id: int) -> tuple[TelegramAccountModel, UserModel]:
    row = db.execute(
        select(TelegramAccountModel, UserModel)
        .join(UserModel, TelegramAccountModel.user_id == UserModel.id)
        .where(TelegramAccountModel.telegram_user_id == telegram_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="account_unlinked")
    return row[0], row[1]


@router.post("/identity/resolve")
def resolve(
    body: ResolveRequest,
    response: Response,
    _: InternalAuth,
    db: Database,
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> dict[str, object]:
    account, user = _account(db, body.telegram_user_id)
    account.username, account.first_name, account.last_name = (
        body.username,
        body.first_name,
        body.last_name,
    )
    account.language_code, account.bot_started, account.blocked_bot = (
        body.language_code,
        True,
        False,
    )
    account.last_seen_at = datetime.now(UTC)
    db.commit()
    _no_store(response)
    opaque = hmac.new(
        Path(settings.telegram_internal_token_file).read_bytes(), user.id.encode(), hashlib.sha256
    ).hexdigest()[:24]
    return {
        "customer_reference": opaque,
        "account_state": user.status,
        "created": False,
        "locale": body.language_code or "fa",
    }


@router.get("/profile")
def profile(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    account, user = _account(db, x_telegram_subject)
    profile_row = db.get(CustomerProfileModel, user.id)
    _no_store(response)
    display = (
        profile_row.display_name
        if profile_row and profile_row.display_name
        else account.first_name or "مشتری"
    )
    return {
        "display_name": display,
        "telegram_linked": True,
        "account_state": user.status,
        "created_at": user.created_at.isoformat(),
        "locale": profile_row.locale if profile_row and profile_row.locale else "fa",
        "username": account.username,
    }


@router.get("/dashboard")
def dashboard(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    telegram, user = _account(db, x_telegram_subject)
    customer_id = _customer_id(db, x_telegram_subject)
    profile_row = db.get(CustomerProfileModel, customer_id)
    service_items = customer_service_summaries(db, customer_id, 100)
    active = [item for item in service_items if item.lifecycle == "ACTIVE"]
    nearest = min((item.expires_at for item in active if item.expires_at is not None), default=None)
    try:
        wallet_data = customer_wallet_projection(db, customer_id)
        balance_rial = int(wallet_data["available_balance_rial"])
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="dashboard_unavailable") from exc
    if balance_rial % 10:
        raise HTTPException(status_code=503, detail="wallet_precision_unavailable")
    _no_store(response)
    return {
        "display_name": (profile_row.display_name if profile_row else None)
        or telegram.first_name
        or "مشتری",
        "account_state": user.status,
        "balance_toman": balance_rial // 10,
        "active_service_count": len(active),
        "nearest_expiry": nearest,
    }


@router.post(
    "/identity/blocked",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def blocked(
    _: InternalAuth, db: Database, x_telegram_subject: Annotated[int, Header(gt=0)]
) -> Response:
    account, _user = _account(db, x_telegram_subject)
    account.blocked_bot = True
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _customer_id(db: Session, telegram_id: int) -> str:
    _telegram, user = _account(db, telegram_id)
    if user.status not in {"ACTIVE", "PENDING"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_restricted")
    return user.id


def _option_label(option: dict[str, Any]) -> str:
    labels = option.get("labels", [])
    if isinstance(labels, dict):
        return str(labels.get("fa") or labels.get("en") or option.get("code", "—"))
    if isinstance(labels, list):
        for label in labels:
            if isinstance(label, dict) and label.get("locale") == "fa":
                return str(label.get("value") or option.get("code"))
    return str(option.get("code", "—"))


def _purchase_idempotency_key(key: str, phase: str, revision: str = "") -> str:
    """Bounded deterministic child keys preserve one Telegram mutation identity per phase."""
    digest = hashlib.sha256(f"{key}|{revision}".encode()).hexdigest()
    return f"tg-purchase:{phase}:{digest}"


def _plan_reference(machine_code: str) -> str:
    """Telegram-safe opaque catalog reference (19 bytes including prefix)."""
    return f"p_{hashlib.sha256(machine_code.encode()).hexdigest()[:16]}"


def _product_for_plan_reference(db: Session, reference: str) -> ProductModel | None:
    matches = [
        product
        for product in db.scalars(select(ProductModel)).all()
        if hmac.compare_digest(_plan_reference(product.machine_code), reference)
    ]
    return matches[0] if len(matches) == 1 else None


def _review_revision(body: NativePurchaseRequest) -> str:
    canonical = json.dumps(
        {
            "plan": body.plan_reference,
            "price": body.reviewed_price_toman,
            "selection": body.reviewed_selection,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _native_order_result(db: Session, order: OrderModel) -> dict[str, object]:
    display = order.snapshot.get("telegram_purchase_display")
    if not isinstance(display, dict):
        raise HTTPException(status_code=409, detail="historical_display_unavailable")
    status_value = order.status
    service = db.scalar(
        select(ServiceModel).where(
            ServiceModel.order_id == order.id,
            ServiceModel.beneficiary_customer_id == order.customer_id,
        )
    )
    service_lifecycle: str | None = None
    delivery_ready = False
    if service is not None:
        detail = customer_service_projection(db, order.customer_id, service.public_reference)
        service_lifecycle = detail.summary.lifecycle if detail is not None else service.lifecycle
        delivery_ready = detail.summary.delivery_ready if detail is not None else False
    if status_value == "REFUNDED":
        purchase_state = "REFUNDED"
    elif order.fulfillment_status == "OPERATOR_REVIEW":
        purchase_state = "OPERATOR_REVIEW"
    elif service is not None and service_lifecycle == "ACTIVE" and delivery_ready:
        purchase_state = "ACTIVE"
    elif service is not None:
        purchase_state = "PENDING_DELIVERY"
    else:
        purchase_state = "PROVISIONING"
    return {
        "outcome": "FINAL" if status_value in {"REFUNDED", "CANCELLED"} else "ACCEPTED",
        "order_reference": order.reference,
        "status": status_value,
        "fulfillment_status": order.fulfillment_status,
        "purchase_state": purchase_state,
        "plan": cast(dict[str, object], display),
        "service_reference": service.public_reference if service else None,
        "service_lifecycle": service_lifecycle,
        "delivery_ready": delivery_ready,
        "expires_at": service.expires_at.isoformat() if service and service.expires_at else None,
        "refunded": status_value == "REFUNDED",
    }


def _purchase_anchor(
    db: Session, customer_id: str, idempotency_key: str
) -> TelegramPurchaseIdempotencyModel:
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    anchor = db.scalar(
        select(TelegramPurchaseIdempotencyModel)
        .where(
            TelegramPurchaseIdempotencyModel.customer_id == customer_id,
            TelegramPurchaseIdempotencyModel.key_hash == key_hash,
        )
        .with_for_update()
    )
    if anchor is not None:
        return anchor
    candidate = TelegramPurchaseIdempotencyModel(
        customer_id=customer_id, key_hash=key_hash, status="REVIEWING"
    )
    try:
        # The unique customer/key constraint is the race arbiter. On PostgreSQL a concurrent insert
        # waits here; the loser rolls back only this savepoint and then locks the winner's row.
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        return candidate
    except IntegrityError:
        anchor = db.scalar(
            select(TelegramPurchaseIdempotencyModel)
            .where(
                TelegramPurchaseIdempotencyModel.customer_id == customer_id,
                TelegramPurchaseIdempotencyModel.key_hash == key_hash,
            )
            .with_for_update()
        )
        if anchor is None:
            raise
        return anchor


def _committed_anchor_order(
    db: Session, anchor: TelegramPurchaseIdempotencyModel
) -> OrderModel | None:
    if anchor.status != "COMMITTED" or not anchor.order_id:
        return None
    order = db.get(OrderModel, anchor.order_id)
    if order is None:
        raise HTTPException(status_code=409, detail="purchase_reconciliation_unavailable")
    return order


def _native_plan(db: Session, product: ProductModel, request: Request) -> dict[str, object]:
    version = db.get(ProductVersionModel, product.current_version_id)
    if not version or version.status != "PUBLISHED":
        raise HTTPException(status_code=404, detail="plan_unavailable")
    if version.product_type != "FIXED_PLAN":
        raise HTTPException(status_code=409, detail="selectable_plan_not_supported")
    options = cast(dict[str, Any], version.options_snapshot)
    locations = cast(list[dict[str, Any]], options.get("location_options", []))
    qualities = cast(list[dict[str, Any]], options.get("quality_options", []))
    enabled_locations = [x for x in locations if x.get("enabled", True)]
    enabled_qualities = [x for x in qualities if x.get("enabled", True)]
    # Until the native option picker ships, expose only genuinely fixed products. Choosing the
    # first option would silently buy a customer selection they never made.
    if len(enabled_locations) != 1 or len(enabled_qualities) != 1:
        raise HTTPException(status_code=409, detail="plan_options_unavailable")
    location, quality = enabled_locations[0], enabled_qualities[0]
    traffic = int(
        options.get("fixed_traffic_bytes") or cast(dict[str, Any], options["traffic"])["minimum"]
    )
    duration = int(
        options.get("fixed_duration_days")
        or cast(dict[str, Any], options["duration_days"])["minimum"]
    )
    devices = int(
        options.get("fixed_device_count") or cast(dict[str, Any], options["devices"])["minimum"]
    )
    selection = QuoteRequest(
        product_id=product.id,
        traffic_bytes=traffic,
        duration_days=duration,
        device_count=devices,
        location_code=str(location["code"]),
        quality_code=str(quality["code"]),
    )
    preview = _price_preview(selection, request, db, datetime.now(UTC))
    localized = _localized(product.localizations, "fa")
    amount = int(str(preview["final_amount_minor"]))
    if amount % 10:
        raise HTTPException(status_code=503, detail="price_precision_unavailable")
    return {
        "reference": _plan_reference(product.machine_code),
        "title": str(localized.get("title") or localized.get("name") or "سرویس"),
        "traffic_gb": traffic // (1024**3),
        "traffic_bytes": traffic,
        "duration_days": duration,
        "device_limit": devices,
        "location_code": str(location["code"]),
        "location_label": _option_label(location),
        "quality_code": str(quality["code"]),
        "quality_label": _option_label(quality),
        "price_toman": amount // 10,
        "selection": selection.model_dump(mode="json", exclude={"product_id", "operation"}),
    }


@router.get("/purchase/catalog")
def purchase_catalog(
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
            items.append(_native_plan(db, product, request))
        except HTTPException:
            continue
    _no_store(response)
    return {"items": items}


@router.get("/purchase/plans/{plan_reference}")
def purchase_plan(
    plan_reference: str,
    request: Request,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    _customer_id(db, x_telegram_subject)
    product = _product_for_plan_reference(db, plan_reference)
    if not product or product.status != "ACTIVE" or not product.customer_visible:
        raise HTTPException(status_code=404, detail="plan_unavailable")
    _no_store(response)
    return _native_plan(db, product, request)


@router.post("/purchase/confirm")
def confirm_native_purchase(
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
    existing_quote_key = _purchase_idempotency_key(idempotency_key, "quote", _review_revision(body))
    existing_idem = db.scalar(
        select(QuoteIdempotencyRecordModel).where(
            QuoteIdempotencyRecordModel.customer_id == customer_id,
            QuoteIdempotencyRecordModel.key_hash
            == hashlib.sha256(f"{customer_id}:{existing_quote_key}".encode()).hexdigest(),
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

    product = _product_for_plan_reference(db, body.plan_reference)
    if not product or product.status != "ACTIVE" or not product.customer_visible:
        raise HTTPException(status_code=409, detail="plan_unavailable")
    plan = _native_plan(db, product, request)
    current_selection = cast(dict[str, int | str], plan["selection"])
    if (
        body.reviewed_price_toman != plan["price_toman"]
        or body.reviewed_selection != current_selection
    ):
        _no_store(response)
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
    quote_body = QuoteRequest(
        product_id=product.id,
        traffic_bytes=int(str(plan["traffic_bytes"])),
        duration_days=int(str(plan["duration_days"])),
        device_count=int(str(plan["device_limit"])),
        location_code=str(plan["location_code"]),
        quality_code=str(plan["quality_code"]),
    )
    session = cast(Any, SimpleNamespace(user_id=customer_id))
    quote = create_quote(
        quote_body,
        request,
        db,
        settings,
        session,
        existing_quote_key,
    )
    quoted_rial = int(str(quote["final_amount_minor"]))
    if quoted_rial % 10 or quoted_rial // 10 != body.reviewed_price_toman:
        plan = {**plan, "price_toman": quoted_rial // 10}
        _no_store(response)
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
    # This immutable customer-display projection keeps historical orders independent of later
    # catalog edits or retirement. It intentionally contains no provider identifiers.
    order_row = db.scalar(
        select(OrderModel).where(OrderModel.reference == order["order_reference"])
    )
    if order_row is not None:
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


@router.get("/purchase/orders/{order_reference}")
def native_purchase_order(
    order_reference: str,
    request: Request,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    order_detail(order_reference, customer_id, db, request)
    order_row = db.scalar(select(OrderModel).where(OrderModel.reference == order_reference))
    if order_row is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    _no_store(response)
    return _native_order_result(db, order_row)


def _service_item(summary: CustomerServiceSummary) -> dict[str, object]:
    data = summary.model_dump()
    entitlement = data["entitlement"]
    return {
        "reference": data["service_reference"],
        "plan_name": data["display_name"],
        "status": data["lifecycle"],
        "status_label": data["lifecycle_label"],
        "expires_at": data["expires_at"],
        "location": entitlement["location_label"],
        "traffic_entitlement_bytes": entitlement["traffic_quota_bytes"],
        "device_limit": entitlement["device_limit"],
        "delivery_ready": data["delivery_ready"],
        "usage": data["usage"],
        "renewable": data["lifecycle"] in {"ACTIVE", "EXPIRED"},
    }


@router.get("/services")
def services(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    _no_store(response)
    return {"items": [_service_item(item) for item in customer_service_summaries(db, customer_id)]}


@router.get("/services/{service_reference}")
def service_detail(
    service_reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    detail = customer_service_projection(
        db, _customer_id(db, x_telegram_subject), service_reference
    )
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="service_not_found")
    _no_store(response)
    item = _service_item(detail.summary)
    item["service_health"] = detail.service_health
    item["eligible_operations"] = detail.eligible_operations
    return item


@router.get("/wallet")
def wallet(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    _no_store(response)
    try:
        projection = customer_wallet_projection(db, customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="wallet_unavailable") from exc
    rial = int(projection["available_balance_rial"])
    if rial % 10:
        raise HTTPException(status_code=503, detail="wallet_precision_unavailable")
    return {"balance_minor": rial // 10, "currency": "TOMAN", "status": projection["status"]}


@router.get("/wallet/transactions")
def transactions(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, object]:
    page = customer_transaction_page(
        db, _customer_id(db, x_telegram_subject), settings, limit=limit, cursor=cursor
    )
    _no_store(response)
    safe_items: list[dict[str, object]] = []
    token = Path(settings.telegram_internal_token_file).read_bytes()
    for item in page["items"]:
        amount_rial = item["amount_rial"]
        if amount_rial is None or int(amount_rial) % 10:
            continue
        safe_items.append(
            {
                "reference": hmac.new(
                    token, str(item["transaction_reference"]).encode(), hashlib.sha256
                ).hexdigest()[:20],
                "amount_minor": int(amount_rial) // 10,
                "currency": "TOMAN",
                "status": item["status"],
                "transaction_type": item["type"],
                "direction": item["direction"],
                "created_at": item["occurred_at"],
            }
        )
    return {"items": safe_items, "next_cursor": page["next_cursor"]}


@router.get("/notification-preferences")
def notification_preferences(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, bool]:
    _customer_id(db, x_telegram_subject)
    _no_store(response)
    return get_preferences(x_telegram_subject, db).model_dump()


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.patch("/notification-preferences/{preference_key}")
def update_notification_preference(
    preference_key: str,
    body: PreferenceUpdate,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> dict[str, bool]:
    _customer_id(db, x_telegram_subject)
    if preference_key not in NotificationPreferencesOut.model_fields:
        raise HTTPException(status_code=400, detail="invalid_preference")
    _no_store(response)
    return patch_preferences(
        x_telegram_subject,
        NotificationPreferencePatch(key=preference_key, enabled=body.enabled),
        db,
        idempotency_key,
    ).model_dump()


class TelegramManualTopupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_rial: int = Field(ge=1_000_000)


def _safe_topup(dto: dict[str, object]) -> dict[str, object]:
    requested = dto["requested_amount_rial"]
    if not isinstance(requested, int):
        raise HTTPException(status_code=503, detail="amount_unavailable")
    amount = requested
    if amount % 10:
        raise HTTPException(status_code=503, detail="amount_precision_unavailable")
    safe = {
        "reference": dto["reference"],
        "amount_toman": amount // 10,
        "status": dto["status"],
        "created_at": dto["created_at"],
        "submitted_at": dto["submitted_at"],
        "version": dto["version"],
    }
    for source, target in (
        ("verified_amount_rial", "verified_amount_toman"),
        ("bonus_amount_rial", "bonus_amount_toman"),
        ("total_credited_rial", "total_credited_toman"),
    ):
        value = dto[source]
        safe[target] = value // 10 if isinstance(value, int) and value % 10 == 0 else None
    return safe


@router.post("/manual-topups")
def create_manual_topup(
    body: TelegramManualTopupCreate,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> dict[str, object]:
    dto = create_manual_topup_for_customer(
        ManualTopupCreateRequest(amount_rial=body.amount_rial, source_channel="TELEGRAM_MINI_APP"),
        _customer_id(db, x_telegram_subject),
        db,
        settings,
        idempotency_key,
    )
    _no_store(response)
    return _safe_topup(dto)


@router.get("/manual-topups")
def list_manual_topups(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    limit: int = 20,
) -> dict[str, object]:
    page = list_manual_topups_for_customer(db, _customer_id(db, x_telegram_subject), limit=limit)
    _no_store(response)
    items_value = page["items"]
    if not isinstance(items_value, list):
        raise HTTPException(status_code=503, detail="topup_list_unavailable")
    raw_items = cast(list[object], items_value)
    items = [cast(dict[str, object], item) for item in raw_items if isinstance(item, dict)]
    return {"items": [_safe_topup(item) for item in items]}


@router.get("/manual-topups/{reference}")
def manual_topup_detail(
    reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    dto = manual_topup_dto(
        db, manual_topup_request(db, reference, _customer_id(db, x_telegram_subject))
    )
    _no_store(response)
    return _safe_topup(dto)


@router.post("/manual-topups/{reference}/cancel")
def cancel_manual_topup(
    reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> dict[str, object]:
    dto = cancel_manual_topup_for_customer(
        db, _customer_id(db, x_telegram_subject), reference, idempotency_key
    )
    _no_store(response)
    return _safe_topup(dto)


@router.get("/manual-topups/{reference}/destination-mode")
def manual_topup_destination_mode(
    reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    row = manual_topup_request(db, reference, _customer_id(db, x_telegram_subject))
    configured = manual_topup_destination_settings(db)
    _no_store(response)
    return {
        "mode": "DIRECT_CARD"
        if configured.customer_display_enabled and row.destination_version_id
        else "SUPPORT_ONLY"
    }


@router.post("/manual-topups/{reference}/receipt")
async def upload_manual_topup_receipt(
    reference: str,
    request: Request,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> dict[str, object]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=422, detail="invalid_receipt")
    raw = await request.body()
    dto = store_receipt_for_customer(
        db,
        settings,
        _customer_id(db, x_telegram_subject),
        reference,
        raw,
        content_type,
        idempotency_key,
    )
    _no_store(response)
    return _safe_topup(dto)
