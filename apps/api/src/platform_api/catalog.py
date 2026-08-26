from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vpnsale_domain.catalog import (
    CATALOG_PRICING_ENGINE_VERSION,
    CatalogError,
    DeviceLimit,
    DurationDays,
    OperationType,
    PlanSelection,
    PricingEngine,
    QuoteStatus,
    TrafficAmount,
    machine_code,
    request_fingerprint,
)
from vpnsale_domain.identity import sanitize_metadata

from platform_api.catalog_models import (
    CustomerPriceQuoteLineModel,
    CustomerPriceQuoteModel,
    PriceListModel,
    PriceListVersionModel,
    PricingRuleModel,
    PricingTierModel,
    ProductCategoryModel,
    ProductModel,
    ProductVersionModel,
    QuoteIdempotencyRecordModel,
)
from platform_api.config import Settings, get_settings
from platform_api.customer_auth.routes import current_customer_session_dependency
from platform_api.database import get_db_session
from platform_api.fulfillment_runtime_models import FulfillmentTargetBindingModel
from platform_api.identity.models import AuditLogModel, CustomerSessionModel
from platform_api.management import require_perm

customer_router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])
admin_router = APIRouter(prefix="/api/v1/admin/catalog", tags=["admin-catalog"])


CATALOG_READ = require_perm("catalog.read")
CATALOG_CREATE = require_perm("catalog.create")
CATALOG_UPDATE = require_perm("catalog.update")
CATALOG_PUBLISH = require_perm("catalog.publish")
PRICING_READ = require_perm("pricing.read")
PRICING_MANAGE = require_perm("pricing.manage")


class ApiError(BaseModel):
    code: str
    message_key: str
    correlation_id: str
    fields: dict[str, str] = Field(default_factory=dict)


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class CategoryRequest(BaseModel):
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]{1,78}$")
    localizations: dict[str, dict[str, str]]
    display_order: int = Field(default=0, ge=0)
    customer_visible: bool = True
    icon_reference: str | None = Field(default=None, max_length=160)
    admin_notes: str | None = Field(default=None, max_length=2000)


class ProductRequest(BaseModel):
    category_id: str
    machine_code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,78}$")
    localizations: dict[str, dict[str, str]]
    display_order: int = Field(default=0, ge=0)
    customer_visible: bool = True
    availability: dict[str, object] = Field(default_factory=dict)
    admin_notes: str | None = Field(default=None, max_length=2000)


class ProductVersionRequest(BaseModel):
    product_type: str = Field(pattern="^(FIXED_PLAN|CUSTOM_PLAN)$")
    definition_snapshot: dict[str, object] = Field(default_factory=dict)
    options_snapshot: dict[str, object]
    constraints_snapshot: list[object] = Field(default_factory=list)
    fulfillment_requirements_snapshot: list[object] = Field(default_factory=list)


class PriceListRequest(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,78}$")
    scope: str = "DEFAULT_RETAIL"
    active: bool = True


class PriceListVersionRequest(BaseModel):
    currency: str = Field(default="IRR", pattern=r"^[A-Z]{3,8}$")
    segment_key: str | None = Field(default=None, max_length=80)
    priority: int = Field(default=100, ge=0)
    active_from: datetime
    active_until: datetime | None = None
    active: bool = True


class PricingRuleRequest(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,78}$")
    rule_type: str
    operation: str | None = None
    selector_code: str | None = None
    amount_minor: int = Field(default=0, ge=0)
    unit_size: int = Field(default=1, gt=0)
    percentage_basis_points: int = Field(default=0, ge=-10000, le=100000)
    priority: int = Field(default=100, ge=0)
    tiers: list[dict[str, int | None]] = Field(default_factory=list)
    customer_label: dict[str, object] = Field(default_factory=dict)


class QuoteRequest(BaseModel):
    product_id: str
    operation: OperationType = OperationType.NEW_PURCHASE
    traffic_bytes: int = Field(gt=0)
    duration_days: int = Field(gt=0)
    device_count: int = Field(gt=0)
    location_code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,78}$")
    quality_code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,78}$")


class StatusRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=240)


def _cid(request: Request) -> str:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or "local"


def _err(
    status: int, request: Request, code: str, fields: dict[str, str] | None = None
) -> HTTPException:
    return HTTPException(
        status,
        detail=ApiError(
            code=code,
            message_key=f"catalog.{code}",
            correlation_id=_cid(request),
            fields=fields or {},
        ).model_dump(),
    )


def _audit(
    db: Session,
    actor_type: str,
    actor_id: str | None,
    code: str,
    target_type: str,
    target_id: str | None,
    request: Request,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLogModel(
            actor_type=actor_type,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            event_code=code,
            occurred_at=datetime.now(UTC),
            correlation_id=_cid(request),
            metadata_=sanitize_metadata(metadata or {}),
        )
    )


def _localized(data: dict[str, object], locale: str) -> dict[str, object]:
    selected = data.get(locale) or data.get("fa") or data.get("en")
    if isinstance(selected, dict):
        return cast(dict[str, object], selected)
    for value in data.values():
        if isinstance(value, dict):
            return cast(dict[str, object], value)
    return {}


def _quote_view(
    q: CustomerPriceQuoteModel, lines: list[CustomerPriceQuoteLineModel], now: datetime
) -> dict[str, object]:
    status = (
        QuoteStatus.EXPIRED.value
        if q.status == QuoteStatus.ACTIVE.value and q.expires_at.replace(tzinfo=UTC) <= now
        else q.status
    )
    return {
        "quote_reference": q.reference,
        "product_id": q.product_id,
        "product_version_id": q.product_version_id,
        "operation": q.operation,
        "selected_options": q.selected_options,
        "price_list_version_id": q.price_list_version_id,
        "currency": q.currency,
        "subtotal_minor": q.subtotal_minor,
        "components": [
            {
                "code": line.component_code,
                "label": line.label,
                "amount_minor": line.amount_minor,
                "order": line.display_order,
            }
            for line in lines
        ],
        "final_amount_minor": q.final_amount_minor,
        "issued_at": q.issued_at.isoformat(),
        "expires_at": q.expires_at.isoformat(),
        "status": status,
        "pricing_engine_version": q.pricing_engine_version,
    }


current_catalog_customer_session = current_customer_session_dependency


def _selection(body: QuoteRequest) -> PlanSelection:
    return PlanSelection(
        TrafficAmount(body.traffic_bytes),
        DurationDays(body.duration_days),
        DeviceLimit(body.device_count),
        body.location_code,
        body.quality_code,
    )


def _active_price_list(
    db: Session, now: datetime, segment: str | None = None
) -> PriceListVersionModel | None:
    rows = db.execute(
        select(PriceListVersionModel)
        .join(PriceListModel, PriceListModel.id == PriceListVersionModel.price_list_id)
        .where(
            PriceListModel.active.is_(True),
            PriceListVersionModel.active.is_(True),
            PriceListVersionModel.active_from <= now,
        )
        .order_by(PriceListVersionModel.priority.asc(), PriceListVersionModel.active_from.desc())
    ).scalars()
    for row in rows:
        if row.active_until and row.active_until.replace(tzinfo=UTC) <= now:
            continue
        if row.segment_key is None or row.segment_key == segment:
            return row
    return None


@customer_router.get("/categories", response_model=Page)
def list_categories(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    locale: str = "fa",
    limit: int = 50,
) -> Page:
    rows = db.execute(
        select(ProductCategoryModel)
        .where(
            ProductCategoryModel.status == "ACTIVE", ProductCategoryModel.customer_visible.is_(True)
        )
        .order_by(ProductCategoryModel.display_order, ProductCategoryModel.slug)
        .limit(min(limit, 100))
    ).scalars()
    return Page(
        items=[
            {
                "id": c.id,
                "slug": c.slug,
                "display_order": c.display_order,
                **_localized(c.localizations, locale),
            }
            for c in rows
        ]
    )


@customer_router.get("/products", response_model=Page)
def list_products(
    db: Annotated[Session, Depends(get_db_session)], locale: str = "fa", limit: int = 50
) -> Page:
    rows = db.execute(
        select(ProductModel)
        .where(
            ProductModel.status == "ACTIVE",
            ProductModel.customer_visible.is_(True),
            ProductModel.current_version_id.is_not(None),
        )
        .order_by(ProductModel.display_order, ProductModel.machine_code)
        .limit(min(limit, 100))
    ).scalars()
    return Page(
        items=[
            {
                "id": p.id,
                "category_id": p.category_id,
                "machine_code": p.machine_code,
                "display_order": p.display_order,
                **_localized(p.localizations, locale),
            }
            for p in rows
        ]
    )


@customer_router.get("/products/{product_id}")
def product_detail(
    product_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    locale: str = "fa",
) -> dict[str, object]:
    p = db.get(ProductModel, product_id)
    if not p or p.status != "ACTIVE" or not p.customer_visible or not p.current_version_id:
        raise _err(404, request, "not_found")
    return {
        "id": p.id,
        "category_id": p.category_id,
        "machine_code": p.machine_code,
        "availability": p.availability,
        **_localized(p.localizations, locale),
    }


@customer_router.get("/products/{product_id}/options")
def product_options(
    product_id: str, request: Request, db: Annotated[Session, Depends(get_db_session)]
) -> dict[str, object]:
    p = db.get(ProductModel, product_id)
    if not p or p.status != "ACTIVE" or not p.current_version_id:
        raise _err(404, request, "not_found")
    v = db.get(ProductVersionModel, p.current_version_id)
    if not v or v.status != "PUBLISHED":
        raise _err(404, request, "not_found")
    return {
        "product_id": p.id,
        "product_version_id": v.id,
        "product_type": v.product_type,
        "options": v.options_snapshot,
    }


def _price_preview(
    body: QuoteRequest, request: Request, db: Session, now: datetime
) -> dict[str, object]:
    p = db.get(ProductModel, body.product_id)
    if not p or p.status != "ACTIVE" or not p.current_version_id:
        raise _err(422, request, "product_unavailable")
    v = db.get(ProductVersionModel, p.current_version_id)
    plv = _active_price_list(db, now)
    if not v or v.status != "PUBLISHED" or not plv:
        raise _err(422, request, "pricing_unavailable")
    selection = _selection(body)
    try:
        from platform_api.catalog_mapping import domain_price_list, domain_product_version

        pricing = PricingEngine().quote(
            domain_product_version(v), domain_price_list(db, plv), selection, body.operation, now
        )
    except CatalogError as exc:
        raise _err(422, request, "invalid_selection", {"selection": str(exc)}) from exc
    return {
        "binding": False,
        "persisted": False,
        "product_id": p.id,
        "product_version_id": v.id,
        "operation": body.operation.value,
        "selected_options": selection.fingerprint(),
        "price_list_version_id": plv.id,
        "currency": pricing.currency,
        "subtotal_minor": pricing.subtotal.amount,
        "components": [
            {
                "code": c.code,
                "label": c.label,
                "amount_minor": c.amount.amount,
                "order": i,
            }
            for i, c in enumerate(pricing.components, start=1)
        ],
        "final_amount_minor": pricing.final.amount,
        "pricing_engine_version": CATALOG_PRICING_ENGINE_VERSION,
        "server_time": now.isoformat(),
        "selection_fingerprint": request_fingerprint(body.model_dump(mode="json")),
    }


@customer_router.post("/quotes/preview")
def preview_quote(
    body: QuoteRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    session: Annotated[CustomerSessionModel, Depends(current_catalog_customer_session)],
) -> dict[str, object]:
    _audit(
        db,
        "customer",
        session.user_id,
        "catalog.quote.preview_requested",
        "product",
        body.product_id,
        request,
        {"operation": body.operation.value},
    )
    return _price_preview(body, request, db, datetime.now(UTC))


@customer_router.post("/quotes")
def create_quote(
    body: QuoteRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[CustomerSessionModel, Depends(current_catalog_customer_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    if idempotency_key and len(idempotency_key) > settings.catalog_quote_idempotency_key_max_length:
        raise _err(422, request, "invalid_idempotency_key")
    now = datetime.now(UTC)
    fingerprint = request_fingerprint(body.model_dump(mode="json"))
    key_hash = ""
    if idempotency_key:
        key_hash = hashlib.sha256(f"{session.user_id}:{idempotency_key}".encode()).hexdigest()
        existing = db.scalar(
            select(QuoteIdempotencyRecordModel).where(
                QuoteIdempotencyRecordModel.customer_id == session.user_id,
                QuoteIdempotencyRecordModel.key_hash == key_hash,
            )
        )
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise _err(409, request, "idempotency_conflict")
            if existing.quote_id:
                q = db.get(CustomerPriceQuoteModel, existing.quote_id)
                if q:
                    lines = list(
                        db.execute(
                            select(CustomerPriceQuoteLineModel)
                            .where(CustomerPriceQuoteLineModel.quote_id == q.id)
                            .order_by(CustomerPriceQuoteLineModel.display_order)
                        ).scalars()
                    )
                    return _quote_view(q, lines, now)
    preview = _price_preview(body, request, db, now)
    preview_components = cast(list[dict[str, str | int]], preview["components"])
    preview_subtotal = cast(int, preview["subtotal_minor"])
    preview_final = cast(int, preview["final_amount_minor"])
    p = db.get(ProductModel, body.product_id)
    v = db.get(ProductVersionModel, preview["product_version_id"])
    plv = db.get(PriceListVersionModel, preview["price_list_version_id"])
    if not p or not v or not plv:
        raise _err(422, request, "pricing_unavailable")
    selection = _selection(body)
    from platform_api.services import resolve_allocation_policy_for_product

    allocation = resolve_allocation_policy_for_product(
        db,
        product_version_id=v.id,
        plan_reference=p.machine_code,
        location=selection.location_code,
    )
    if allocation is None:
        legacy_binding = db.scalar(
            select(FulfillmentTargetBindingModel.id).where(
                FulfillmentTargetBindingModel.product_version_id == v.id,
                FulfillmentTargetBindingModel.location_code == selection.location_code,
                FulfillmentTargetBindingModel.quality_code == selection.quality_code,
                FulfillmentTargetBindingModel.active.is_(True),
            )
        )
        if legacy_binding is not None:
            allocation = {
                "mode": "LEGACY_BINDING_V1",
                "required_target_count": 1,
                "identity_strategy": "PER_TARGET",
                "plan_reference": p.machine_code,
                "location": selection.location_code,
            }
    if allocation is None:
        raise _err(422, request, "allocation_unavailable")
    quote = CustomerPriceQuoteModel(
        product_id=p.id,
        product_version_id=v.id,
        customer_id=session.user_id,
        reference=hashlib.sha256(f"{p.id}{session.user_id}{now.timestamp()}".encode()).hexdigest()[
            :32
        ],
        operation=body.operation.value,
        selected_options=selection.fingerprint(),
        price_list_version_id=plv.id,
        currency=str(preview["currency"]),
        subtotal_minor=preview_subtotal,
        final_amount_minor=preview_final,
        pricing_engine_version=CATALOG_PRICING_ENGINE_VERSION,
        status="ACTIVE",
        issued_at=now,
        expires_at=now + timedelta(seconds=settings.catalog_quote_lifetime_seconds),
        validation_summary={"validated": True, "allocation": allocation},
    )
    db.add(quote)
    db.flush()
    lines = [
        CustomerPriceQuoteLineModel(
            quote_id=quote.id,
            component_code=str(c["code"]),
            label=str(c["label"]),
            amount_minor=cast(int, c["amount_minor"]),
            display_order=cast(int, c["order"]),
        )
        for c in preview_components
    ]
    db.add_all(lines)
    if idempotency_key:
        db.add(
            QuoteIdempotencyRecordModel(
                customer_id=session.user_id,
                key_hash=key_hash,
                request_fingerprint=fingerprint,
                quote_id=quote.id,
                expires_at=now
                + timedelta(seconds=settings.catalog_quote_idempotency_lifetime_seconds),
            )
        )
    _audit(
        db,
        "customer",
        session.user_id,
        "catalog.quote.issued",
        "customer_price_quote",
        quote.id,
        request,
        {"product_id": p.id, "amount_minor": quote.final_amount_minor, "currency": quote.currency},
    )
    return _quote_view(quote, lines, now)


@customer_router.get("/quotes/{quote_reference}")
def get_quote(
    quote_reference: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    session: Annotated[CustomerSessionModel, Depends(current_catalog_customer_session)],
) -> dict[str, object]:
    q = db.scalar(
        select(CustomerPriceQuoteModel).where(CustomerPriceQuoteModel.reference == quote_reference)
    )
    if not q or q.customer_id != session.user_id:
        raise _err(404, request, "not_found")
    lines = list(
        db.execute(
            select(CustomerPriceQuoteLineModel)
            .where(CustomerPriceQuoteLineModel.quote_id == q.id)
            .order_by(CustomerPriceQuoteLineModel.display_order)
        ).scalars()
    )
    return _quote_view(q, lines, datetime.now(UTC))


@admin_router.post("/categories")
def create_category(
    body: CategoryRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(CATALOG_CREATE)],
) -> dict[str, object]:
    c = ProductCategoryModel(
        slug=machine_code(body.slug),
        localizations=body.localizations,
        display_order=body.display_order,
        customer_visible=body.customer_visible,
        icon_reference=body.icon_reference,
        admin_notes=body.admin_notes,
    )
    db.add(c)
    try:
        db.flush()
    except IntegrityError as exc:
        raise _err(409, request, "duplicate_category") from exc
    _audit(db, "admin", admin.id, "catalog.category.created", "product_category", c.id, request)
    return {"id": c.id, "slug": c.slug, "status": c.status}


@admin_router.get("/categories", response_model=Page)
def admin_categories(
    db: Annotated[Session, Depends(get_db_session)], admin: Annotated[Any, Depends(CATALOG_READ)]
) -> Page:
    rows = db.execute(
        select(ProductCategoryModel).order_by(ProductCategoryModel.display_order)
    ).scalars()
    return Page(
        items=[
            {"id": c.id, "slug": c.slug, "status": c.status, "admin_notes": c.admin_notes}
            for c in rows
        ]
    )


@admin_router.post("/categories/{category_id}/activate")
def activate_category(
    category_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(CATALOG_UPDATE)],
) -> dict[str, object]:
    c = db.get(ProductCategoryModel, category_id)
    if not c:
        raise _err(404, request, "not_found")
    c.status = "ACTIVE"
    c.updated_at = datetime.now(UTC)
    c.version += 1
    _audit(db, "admin", admin.id, "catalog.category.updated", "product_category", c.id, request)
    return {"id": c.id, "status": c.status}


@admin_router.get("/products", response_model=Page)
def admin_products(
    db: Annotated[Session, Depends(get_db_session)],
    _admin: Annotated[Any, Depends(CATALOG_READ)],
    status_filter: str | None = None,
    limit: int = 100,
) -> Page:
    statement = select(ProductModel)
    if status_filter:
        statement = statement.where(ProductModel.status == status_filter.upper())
    rows = db.scalars(
        statement.order_by(ProductModel.display_order, ProductModel.machine_code).limit(
            min(max(limit, 1), 100)
        )
    ).all()
    return Page(
        items=[
            {
                "id": row.id,
                "category_id": row.category_id,
                "machine_code": row.machine_code,
                "status": row.status,
                "current_version_id": row.current_version_id,
                "customer_visible": row.customer_visible,
                "display_order": row.display_order,
                "localizations": row.localizations,
                "availability": row.availability,
                "updated_at": row.updated_at,
                "version": row.version,
            }
            for row in rows
        ]
    )


@admin_router.get("/products/{product_id}/versions", response_model=Page)
def admin_product_versions(
    product_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    _admin: Annotated[Any, Depends(CATALOG_READ)],
) -> Page:
    if db.get(ProductModel, product_id) is None:
        raise _err(404, request, "not_found")
    rows = db.scalars(
        select(ProductVersionModel)
        .where(ProductVersionModel.product_id == product_id)
        .order_by(ProductVersionModel.version_number.desc())
    ).all()
    return Page(
        items=[
            {
                "id": row.id,
                "product_id": row.product_id,
                "version_number": row.version_number,
                "status": row.status,
                "product_type": row.product_type,
                "definition_snapshot": row.definition_snapshot,
                "options_snapshot": row.options_snapshot,
                "constraints_snapshot": row.constraints_snapshot,
                "fulfillment_requirements_snapshot": row.fulfillment_requirements_snapshot,
                "created_at": row.created_at,
                "published_at": row.published_at,
                "retired_at": row.retired_at,
            }
            for row in rows
        ]
    )


@admin_router.post("/products")
def create_product(
    body: ProductRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(CATALOG_CREATE)],
) -> dict[str, object]:
    p = ProductModel(
        category_id=body.category_id,
        machine_code=machine_code(body.machine_code),
        localizations=body.localizations,
        display_order=body.display_order,
        customer_visible=body.customer_visible,
        availability=body.availability,
        admin_notes=body.admin_notes,
    )
    db.add(p)
    try:
        db.flush()
    except IntegrityError as exc:
        raise _err(409, request, "duplicate_product") from exc
    _audit(db, "admin", admin.id, "catalog.product.created", "product", p.id, request)
    return {"id": p.id, "machine_code": p.machine_code, "status": p.status}


@admin_router.post("/products/{product_id}/versions")
def create_version(
    product_id: str,
    body: ProductVersionRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(CATALOG_UPDATE)],
) -> dict[str, object]:
    p = db.get(ProductModel, product_id)
    if not p:
        raise _err(404, request, "not_found")
    next_no = (
        db.scalar(
            select(ProductVersionModel.version_number)
            .where(ProductVersionModel.product_id == product_id)
            .order_by(ProductVersionModel.version_number.desc())
            .limit(1)
        )
        or 0
    ) + 1
    v = ProductVersionModel(
        product_id=product_id,
        version_number=next_no,
        product_type=body.product_type,
        definition_snapshot=body.definition_snapshot,
        options_snapshot=body.options_snapshot,
        constraints_snapshot=body.constraints_snapshot,
        fulfillment_requirements_snapshot=body.fulfillment_requirements_snapshot,
    )
    db.add(v)
    db.flush()
    _audit(
        db,
        "admin",
        admin.id,
        "catalog.product_version.draft_created",
        "product_version",
        v.id,
        request,
    )
    return {"id": v.id, "version_number": v.version_number, "status": v.status}


@admin_router.post("/products/{product_id}/versions/{version_id}/publish")
def publish_version(
    product_id: str,
    version_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(CATALOG_PUBLISH)],
) -> dict[str, object]:
    p = db.get(ProductModel, product_id)
    v = db.get(ProductVersionModel, version_id)
    if not p or not v or v.product_id != product_id:
        raise _err(404, request, "not_found")
    if v.status != "DRAFT" or not v.fulfillment_requirements_snapshot:
        raise _err(422, request, "invalid_publication")
    db.execute(
        update(ProductVersionModel)
        .where(
            ProductVersionModel.product_id == product_id, ProductVersionModel.status == "PUBLISHED"
        )
        .values(status="SUPERSEDED")
    )
    v.status = "PUBLISHED"
    v.published_at = datetime.now(UTC)
    p.current_version_id = v.id
    p.status = "ACTIVE"
    p.updated_at = datetime.now(UTC)
    _audit(
        db, "admin", admin.id, "catalog.product_version.published", "product_version", v.id, request
    )
    return {"id": v.id, "status": v.status, "product_status": p.status}


@admin_router.post("/products/{product_id}/pause")
def pause_product(
    product_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(CATALOG_UPDATE)],
) -> dict[str, object]:
    p = db.get(ProductModel, product_id)
    if not p:
        raise _err(404, request, "not_found")
    p.status = "PAUSED"
    _audit(db, "admin", admin.id, "catalog.product.paused", "product", p.id, request)
    return {"id": p.id, "status": p.status}


@admin_router.post("/price-lists")
def create_price_list(
    body: PriceListRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(PRICING_MANAGE)],
) -> dict[str, object]:
    pl = PriceListModel(key=machine_code(body.key), scope=body.scope, active=body.active)
    db.add(pl)
    db.flush()
    _audit(db, "admin", admin.id, "catalog.price_list.created", "price_list", pl.id, request)
    return {"id": pl.id, "key": pl.key}


@admin_router.post("/price-lists/{price_list_id}/versions")
def create_price_list_version(
    price_list_id: str,
    body: PriceListVersionRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(PRICING_MANAGE)],
) -> dict[str, object]:
    next_no = (
        db.scalar(
            select(PriceListVersionModel.version_number)
            .where(PriceListVersionModel.price_list_id == price_list_id)
            .order_by(PriceListVersionModel.version_number.desc())
            .limit(1)
        )
        or 0
    ) + 1
    plv = PriceListVersionModel(
        price_list_id=price_list_id,
        version_number=next_no,
        currency=body.currency,
        segment_key=body.segment_key,
        priority=body.priority,
        active=body.active,
        active_from=body.active_from,
        active_until=body.active_until,
    )
    db.add(plv)
    db.flush()
    _audit(
        db,
        "admin",
        admin.id,
        "catalog.price_list_version.created",
        "price_list_version",
        plv.id,
        request,
    )
    return {"id": plv.id, "version_number": plv.version_number}


@admin_router.post("/price-list-versions/{version_id}/rules")
def create_rule(
    version_id: str,
    body: PricingRuleRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(PRICING_MANAGE)],
) -> dict[str, object]:
    r = PricingRuleModel(
        price_list_version_id=version_id,
        code=machine_code(body.code),
        rule_type=body.rule_type,
        operation=body.operation,
        selector_code=body.selector_code,
        amount_minor=body.amount_minor,
        unit_size=body.unit_size,
        percentage_basis_points=body.percentage_basis_points,
        priority=body.priority,
        customer_label=body.customer_label,
    )
    db.add(r)
    db.flush()
    for t in body.tiers:
        db.add(
            PricingTierModel(
                pricing_rule_id=r.id,
                lower_inclusive=int(t["lower_inclusive"] or 0),
                upper_exclusive=t.get("upper_exclusive"),
                unit_amount_minor=int(t["unit_amount_minor"] or 0),
                priority=int(t["priority"] or 0),
            )
        )
    _audit(
        db,
        "admin",
        admin.id,
        "catalog.pricing_rule.created",
        "pricing_rule",
        r.id,
        request,
        {"amount_minor": r.amount_minor},
    )
    return {"id": r.id, "code": r.code}


@admin_router.post("/preview")
def admin_preview_quote(
    body: QuoteRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Any, Depends(PRICING_READ)],
) -> dict[str, object]:
    now = datetime.now(UTC)
    p = db.get(ProductModel, body.product_id)
    if not p or not p.current_version_id:
        raise _err(404, request, "not_found")
    v = db.get(ProductVersionModel, p.current_version_id)
    plv = _active_price_list(db, now)
    if not v or not plv:
        raise _err(422, request, "pricing_unavailable")
    from platform_api.catalog_mapping import domain_price_list, domain_product_version

    pricing = PricingEngine().quote(
        domain_product_version(v), domain_price_list(db, plv), _selection(body), body.operation, now
    )
    _audit(db, "admin", admin.id, "catalog.preview.executed", "product", p.id, request)
    return {
        "preview": True,
        "currency": pricing.currency,
        "final_amount_minor": pricing.final.amount,
        "components": [
            {"code": c.code, "amount_minor": c.amount.amount} for c in pricing.components
        ],
    }
