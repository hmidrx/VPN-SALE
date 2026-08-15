from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.delivery import (
    DeliveryError,
    DeliveryOutputFormat,
    DeliveryProtocol,
    hash_token,
    issue_subscription_token,
    render_qr_png,
)

from .customer_auth.routes import current_customer_session_dependency
from .database import get_db_session
from .delivery_models import (
    DeliveryAccessEventModel,
    DeliveryRevisionModel,
    DeliverySubscriptionModel,
    DeliverySubscriptionTokenModel,
)
from .delivery_secrets import DeliveryPayloadCipher, DeliveryPayloadError
from .identity.models import CustomerSessionModel
from .management import require_perm
from .service_models import ServiceModel
from .services import customer_service_projection

NO_STORE = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}

admin_router = APIRouter(prefix="/api/v1/admin/delivery", tags=["admin-delivery"])
customer_router = APIRouter(prefix="/api/v1/customer/delivery", tags=["customer-delivery"])
public_router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class DeliveryErrorResponse(BaseModel):
    code: str
    message: str


class DeliveryProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str
    title: str
    status: str
    current_version: int | None
    protocol: DeliveryProtocol | None = None


class DeliveryProfileDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    protocol: DeliveryProtocol
    transport: str
    security: str
    public_address: str
    public_port: int = Field(ge=1, le=65535)
    remark_template: str = Field(min_length=1, max_length=160)


class DeliveryProfileValidationResponse(BaseModel):
    valid: bool
    errors: list[str]
    renderer_contracts: dict[str, str]


class DeliverySummary(BaseModel):
    service_reference: str
    status: str
    delivery_ready: bool
    connections: list[dict[str, str]]
    formats: list[DeliveryOutputFormat]


class SubscriptionStatus(BaseModel):
    service_reference: str
    status: str
    stable_urls: dict[str, str]
    token_visible_once: str | None = None


def _decrypt_revision(service_id: str, revision: DeliveryRevisionModel) -> tuple[str, ...]:
    try:
        return DeliveryPayloadCipher.from_environment().decrypt(
            service_id,
            revision.encryption_key_version,
            revision.encrypted_payload,
            revision.payload_sha256,
        )
    except DeliveryPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_CREDENTIAL_UNAVAILABLE"},
        ) from exc


def _active_revision(db: Session, service_id: str) -> DeliveryRevisionModel | None:
    return db.scalar(
        select(DeliveryRevisionModel)
        .where(
            DeliveryRevisionModel.service_id == service_id,
            DeliveryRevisionModel.status == "ACTIVE",
        )
        .order_by(DeliveryRevisionModel.revision_number.desc())
        .limit(1)
    )


def customer_delivery_links(
    db: Session, customer_id: str, service_reference: str
) -> tuple[ServiceModel, tuple[str, ...]]:
    service = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == service_reference,
            ServiceModel.beneficiary_customer_id == customer_id,
        )
    )
    if service is None:
        raise HTTPException(status_code=404, detail={"code": "SERVICE_NOT_FOUND"})
    projection = customer_service_projection(db, customer_id, service_reference)
    if projection is None or not projection.summary.delivery_ready or service.lifecycle != "ACTIVE":
        raise HTTPException(status_code=409, detail={"code": "DELIVERY_NOT_READY"})
    revision = _active_revision(db, service.id)
    if revision is None:
        raise HTTPException(status_code=409, detail={"code": "DELIVERY_NOT_READY"})
    return service, _decrypt_revision(service.id, revision)


@admin_router.get("/profiles", response_model=list[DeliveryProfileSummary])
async def list_profiles(
    _: Annotated[object, Depends(require_perm("delivery_profiles.read"))],
) -> list[DeliveryProfileSummary]:
    return []


@admin_router.post("/profiles/validate", response_model=DeliveryProfileValidationResponse)
async def validate_profile(
    payload: DeliveryProfileDraftRequest,
    _: Annotated[object, Depends(require_perm("delivery_profiles.manage"))],
) -> DeliveryProfileValidationResponse:
    errors: list[str] = []
    if "://" in payload.public_address or "@" in payload.public_address:
        errors.append("DELIVERY_ADDRESS_INVALID")
    if payload.security == "REALITY" and payload.protocol == DeliveryProtocol.VMESS:
        errors.append("DELIVERY_PROFILE_INCOMPATIBLE")
    return DeliveryProfileValidationResponse(
        valid=not errors, errors=errors, renderer_contracts=_renderer_contracts()
    )


@admin_router.get("/compatibility", response_model=dict[str, object])
async def compatibility_matrix(
    _: Annotated[object, Depends(require_perm("delivery_compatibility.read"))],
) -> dict[str, object]:
    return {
        "renderer_contracts": _renderer_contracts(),
        "legacy_clash": "Trojan/VMess/Shadowsocks TLS or none only; VLESS/REALITY/XHTTP rejected",
    }


@admin_router.get("/services/{service_reference}/delivery", response_model=DeliverySummary)
async def admin_service_delivery(
    service_reference: str,
    _: Annotated[object, Depends(require_perm("service_delivery.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> DeliverySummary:
    service = db.scalar(
        select(ServiceModel).where(ServiceModel.public_reference == service_reference)
    )
    if service is None:
        raise HTTPException(status_code=404, detail={"code": "SERVICE_NOT_FOUND"})
    revision = _active_revision(db, service.id)
    return DeliverySummary(
        service_reference=service_reference,
        status=service.lifecycle,
        delivery_ready=service.lifecycle == "ACTIVE" and revision is not None,
        connections=[],
        formats=(
            [DeliveryOutputFormat.PLAIN_LINKS, DeliveryOutputFormat.BASE64_LINKS]
            if service.lifecycle == "ACTIVE" and revision is not None
            else []
        ),
    )


@customer_router.get("/services/{service_reference}", response_model=DeliverySummary)
async def customer_service_delivery(
    service_reference: str,
    customer_session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    response: Response,
) -> DeliverySummary:
    service, links = customer_delivery_links(db, customer_session.user_id, service_reference)
    for key, value in NO_STORE.items():
        response.headers[key] = value
    return DeliverySummary(
        service_reference=service.public_reference,
        status=service.lifecycle,
        delivery_ready=True,
        connections=[{"uri": link} for link in links],
        formats=[DeliveryOutputFormat.PLAIN_LINKS, DeliveryOutputFormat.BASE64_LINKS],
    )


@customer_router.post(
    "/services/{service_reference}/subscription", response_model=SubscriptionStatus
)
async def issue_customer_subscription(
    service_reference: str,
    customer_session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    response: Response,
) -> SubscriptionStatus:
    service, _links = customer_delivery_links(db, customer_session.user_id, service_reference)
    now = datetime.now(UTC)
    subscription = db.scalar(
        select(DeliverySubscriptionModel)
        .where(
            DeliverySubscriptionModel.service_id == service.id,
            DeliverySubscriptionModel.scope == "CUSTOMER",
        )
        .with_for_update()
    )
    if subscription is None:
        subscription = DeliverySubscriptionModel(
            public_reference=f"sub_{uuid4().hex[:24]}",
            service_id=service.id,
            scope="CUSTOMER",
            status="ACTIVE",
            active_token_hash=None,
            created_at=now,
            updated_at=now,
        )
        db.add(subscription)
        db.flush()
    if subscription.active_token_hash:
        old = db.scalar(
            select(DeliverySubscriptionTokenModel).where(
                DeliverySubscriptionTokenModel.token_hash == subscription.active_token_hash
            )
        )
        if old is not None and old.status == "ACTIVE":
            old.status = "REVOKED"
            old.revoked_at = now
    token, token_record = issue_subscription_token(now)
    row = DeliverySubscriptionTokenModel(
        subscription_id=subscription.id,
        token_hash=token_record.token_hash,
        status="ACTIVE",
        issued_at=now,
    )
    db.add(row)
    subscription.active_token_hash = token_record.token_hash
    subscription.status = "ACTIVE"
    subscription.updated_at = now
    db.add(
        DeliveryAccessEventModel(
            subscription_id=subscription.id,
            service_id=service.id,
            actor_type="CUSTOMER",
            action="SUBSCRIPTION_ISSUED",
            outcome="SUCCESS",
            safe_metadata={},
            created_at=now,
        )
    )
    db.commit()
    for key, value in NO_STORE.items():
        response.headers[key] = value
    return SubscriptionStatus(
        service_reference=service_reference,
        status="ACTIVE",
        stable_urls=_stable_urls(token),
        token_visible_once=token,
    )


@customer_router.get("/qr", responses={200: {"content": {"image/png": {}}}})
async def qr(
    payload: Annotated[str, Header(max_length=2048)],
    _: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
) -> Response:
    try:
        png = render_qr_png(payload)
    except DeliveryError as exc:
        return Response(
            content=DeliveryErrorResponse(
                code=exc.code.value, message=exc.safe_message
            ).model_dump_json(),
            status_code=status.HTTP_400_BAD_REQUEST,
            media_type="application/json",
            headers=NO_STORE,
        )
    return Response(content=png, media_type="image/png", headers=NO_STORE)


@public_router.get("/{opaque_token}")
def subscription_default(
    opaque_token: str, db: Annotated[Session, Depends(get_db_session)]
) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.BASE64_LINKS, db)


@public_router.get("/{opaque_token}/links")
def subscription_links(
    opaque_token: str, db: Annotated[Session, Depends(get_db_session)]
) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.PLAIN_LINKS, db)


@public_router.get("/{opaque_token}/mihomo")
def subscription_mihomo(
    opaque_token: str, db: Annotated[Session, Depends(get_db_session)]
) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.MIHOMO, db)


@public_router.get("/{opaque_token}/clash")
def subscription_clash(
    opaque_token: str, db: Annotated[Session, Depends(get_db_session)]
) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.CLASH_LEGACY, db)


@public_router.get("/{opaque_token}/sing-box")
def subscription_sing_box(
    opaque_token: str, db: Annotated[Session, Depends(get_db_session)]
) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.SING_BOX, db)


def _subscription_not_found() -> Response:
    return Response(
        content='{"code":"SUBSCRIPTION_NOT_FOUND","message":"subscription unavailable"}',
        status_code=status.HTTP_404_NOT_FOUND,
        media_type="application/json",
        headers=NO_STORE,
    )


def _subscription_response(
    opaque_token: str, fmt: DeliveryOutputFormat, db: Session
) -> Response:
    if len(opaque_token) < 43 or "/" in opaque_token:
        return _subscription_not_found()
    token_hash = hash_token(opaque_token)
    token_row = db.scalar(
        select(DeliverySubscriptionTokenModel).where(
            DeliverySubscriptionTokenModel.token_hash == token_hash,
            DeliverySubscriptionTokenModel.status == "ACTIVE",
        )
    )
    if token_row is None:
        return _subscription_not_found()
    subscription = db.get(DeliverySubscriptionModel, token_row.subscription_id)
    if (
        subscription is None
        or subscription.status != "ACTIVE"
        or subscription.active_token_hash != token_hash
    ):
        return _subscription_not_found()
    service = db.get(ServiceModel, subscription.service_id)
    if service is None or service.lifecycle != "ACTIVE":
        return _subscription_not_found()
    revision = _active_revision(db, service.id)
    if revision is None:
        return _subscription_not_found()
    try:
        links = _decrypt_revision(service.id, revision)
    except HTTPException:
        return Response(
            content='{"code":"SERVICE_UNAVAILABLE","message":"subscription unavailable"}',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json",
            headers=NO_STORE,
        )
    if fmt not in {DeliveryOutputFormat.PLAIN_LINKS, DeliveryOutputFormat.BASE64_LINKS}:
        return Response(
            content='{"code":"SUBSCRIPTION_FORMAT_UNSUPPORTED","message":"format unavailable"}',
            status_code=status.HTTP_400_BAD_REQUEST,
            media_type="application/json",
            headers=NO_STORE,
        )
    plain = "\n".join(links) + "\n"
    content = (
        plain
        if fmt is DeliveryOutputFormat.PLAIN_LINKS
        else base64.b64encode(plain.encode()).decode()
    )
    db.add(
        DeliveryAccessEventModel(
            subscription_id=subscription.id,
            service_id=service.id,
            actor_type="SUBSCRIPTION",
            action="READ",
            outcome="SUCCESS",
            safe_metadata={"format": fmt.value},
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    return Response(content=content, media_type="text/plain; charset=utf-8", headers=NO_STORE)


def _stable_urls(token: str) -> dict[str, str]:
    return {
        "base64": f"/subscriptions/{token}",
        "links": f"/subscriptions/{token}/links",
    }


def _renderer_contracts() -> dict[str, str]:
    return {
        "xray": "Project X transport/protocol docs checked 2026-07-18",
        "shadowsocks": "SIP002/SIP022 docs checked 2026-07-18",
        "mihomo": "MetaCubeX/mihomo v1.19.28 release/docs checked 2026-07-18",
        "sing_box": "SagerNet/sing-box stable docs/releases checked 2026-07-18",
    }
