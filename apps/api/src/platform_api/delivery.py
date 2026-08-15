from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.delivery import (
    DeliveryError,
    DeliveryOutputFormat,
    DeliveryProtocol,
    render_qr_png,
)

from platform_api.customer_auth.routes import current_customer_session_dependency
from platform_api.database import get_db_session
from platform_api.delivery_models import DeliveryProfileVersionModel, DeliveryRevisionModel
from platform_api.delivery_resolution import (
    RENDERER_VERSION,
    delivery_profile_from_model,
    render_service_connection,
)
from platform_api.identity.models import CustomerSessionModel
from platform_api.service_models import (
    AllocationTargetModel,
    ServiceAttachmentModel,
    ServiceModel,
)

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


@admin_router.get("/profiles", response_model=list[DeliveryProfileSummary])
async def list_profiles() -> list[DeliveryProfileSummary]:
    return []


@admin_router.post("/profiles/validate", response_model=DeliveryProfileValidationResponse)
async def validate_profile(
    payload: DeliveryProfileDraftRequest,
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
async def compatibility_matrix() -> dict[str, object]:
    return {
        "renderer_contracts": _renderer_contracts(),
        "legacy_clash": "Trojan/VMess/Shadowsocks TLS or none only; VLESS/REALITY/XHTTP rejected",
    }


@admin_router.get("/services/{service_reference}/delivery", response_model=DeliverySummary)
async def admin_service_delivery(service_reference: str) -> DeliverySummary:
    return _safe_summary(service_reference)


def _owned_service(db: Session, customer_id: str, service_reference: str) -> ServiceModel:
    service = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == service_reference,
            ServiceModel.beneficiary_customer_id == customer_id,
        )
    )
    if service is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "SERVICE_NOT_FOUND"},
        )
    return service


def _required_attachments(db: Session, service_id: str) -> list[ServiceAttachmentModel]:
    return list(
        db.scalars(
            select(ServiceAttachmentModel).where(
                ServiceAttachmentModel.service_id == service_id,
                ServiceAttachmentModel.required.is_(True),
            )
        )
    )


def _verified_required_attachments(db: Session, service_id: str) -> bool:
    attachments = _required_attachments(db, service_id)
    return bool(attachments) and all(
        item.status == "VERIFIED" and item.verification_status == "VERIFIED" for item in attachments
    )


def _render_active_delivery(db: Session, service: ServiceModel) -> str:
    attachments = _required_attachments(db, service.id)
    if len(attachments) != 1:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_ATTACHMENT_CARDINALITY_INVALID"},
        )
    attachment = attachments[0]
    revision = db.scalar(
        select(DeliveryRevisionModel)
        .where(
            DeliveryRevisionModel.service_id == service.id,
            DeliveryRevisionModel.status == "ACTIVE",
        )
        .order_by(DeliveryRevisionModel.revision_number.desc())
        .limit(1)
    )
    if revision is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_REVISION_MISSING"},
        )
    snapshot = revision.attachment_snapshot
    attachment_id = snapshot.get("attachment_id")
    target_id = snapshot.get("allocation_target_id")
    profile_version_id = snapshot.get("profile_version_id")
    if (
        attachment_id != attachment.id
        or target_id != attachment.allocation_target_id
        or not isinstance(profile_version_id, str)
    ):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_REVISION_STALE"},
        )
    if revision.renderer_versions.get("URI") != RENDERER_VERSION:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_RENDERER_UNAVAILABLE"},
        )
    if revision.compatibility_state.get("provider_host_used") is not False:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_REVISION_UNSAFE"},
        )
    target = db.get(AllocationTargetModel, target_id)
    profile_row = db.get(DeliveryProfileVersionModel, profile_version_id)
    if target is None or profile_row is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_REVISION_STALE"},
        )
    try:
        profile = delivery_profile_from_model(profile_row, require_published=False)
        uri, fingerprint = render_service_connection(
            service,
            attachment,
            target,
            profile,
            require_verified=True,
        )
    except (DeliveryError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_REVISION_STALE"},
        ) from exc
    expected_fingerprint = revision.credential_fingerprints.get(attachment.id)
    if (
        not isinstance(expected_fingerprint, str)
        or not hmac.compare_digest(expected_fingerprint, fingerprint)
        or not hmac.compare_digest(profile_version_id, str(profile.version_id))
    ):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_REVISION_STALE"},
        )
    return uri


@customer_router.get("/services/{service_reference}", response_model=DeliverySummary)
def customer_service_delivery(
    service_reference: str,
    response: Response,
    session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
) -> DeliverySummary:
    response.headers.update(NO_STORE)
    service = _owned_service(db, session.user_id, service_reference)
    if service.lifecycle != "ACTIVE" or not _verified_required_attachments(db, service.id):
        return DeliverySummary(
            service_reference=service.public_reference,
            status="PENDING_DELIVERY",
            delivery_ready=False,
            connections=[],
            formats=[],
        )
    uri = _render_active_delivery(db, service)
    return DeliverySummary(
        service_reference=service.public_reference,
        status="ACTIVE",
        delivery_ready=True,
        connections=[{"uri": uri}],
        formats=[DeliveryOutputFormat.URI, DeliveryOutputFormat.PLAIN_LINKS],
    )


@customer_router.post(
    "/services/{service_reference}/subscription",
    response_model=SubscriptionStatus,
)
async def issue_customer_subscription(service_reference: str) -> SubscriptionStatus:
    del service_reference
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail={"code": "SUBSCRIPTION_PERSISTENCE_NOT_IMPLEMENTED"},
    )


@customer_router.get("/qr", responses={200: {"content": {"image/png": {}}}})
async def qr(payload: Annotated[str, Header(max_length=2048)]) -> Response:
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
async def subscription_default(opaque_token: str) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.BASE64_LINKS)


@public_router.get("/{opaque_token}/links")
async def subscription_links(opaque_token: str) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.PLAIN_LINKS)


@public_router.get("/{opaque_token}/mihomo")
async def subscription_mihomo(opaque_token: str) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.MIHOMO)


@public_router.get("/{opaque_token}/clash")
async def subscription_clash(opaque_token: str) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.CLASH_LEGACY)


@public_router.get("/{opaque_token}/sing-box")
async def subscription_sing_box(opaque_token: str) -> Response:
    return _subscription_response(opaque_token, DeliveryOutputFormat.SING_BOX)


def _subscription_response(opaque_token: str, fmt: DeliveryOutputFormat) -> Response:
    if len(opaque_token) < 43 or "/" in opaque_token:
        return Response(
            content='{"code":"SUBSCRIPTION_NOT_FOUND","message":"subscription unavailable"}',
            status_code=status.HTTP_404_NOT_FOUND,
            media_type="application/json",
            headers=NO_STORE,
        )
    media = {
        DeliveryOutputFormat.PLAIN_LINKS: "text/plain; charset=utf-8",
        DeliveryOutputFormat.BASE64_LINKS: "text/plain; charset=utf-8",
        DeliveryOutputFormat.MIHOMO: "application/yaml; charset=utf-8",
        DeliveryOutputFormat.CLASH_LEGACY: "application/yaml; charset=utf-8",
        DeliveryOutputFormat.SING_BOX: "application/json; charset=utf-8",
    }[fmt]
    return Response(
        content="# delivery subscription requires repository-backed token lookup\n",
        media_type=media,
        headers=NO_STORE,
    )


def _safe_summary(service_reference: str) -> DeliverySummary:
    return DeliverySummary(
        service_reference=service_reference,
        status="METADATA_ONLY",
        delivery_ready=False,
        connections=[],
        formats=[
            DeliveryOutputFormat.PLAIN_LINKS,
            DeliveryOutputFormat.BASE64_LINKS,
            DeliveryOutputFormat.MIHOMO,
            DeliveryOutputFormat.SING_BOX,
        ],
    )


def _renderer_contracts() -> dict[str, str]:
    return {
        "xray": "Project X transport/protocol docs checked 2026-07-18",
        "shadowsocks": "SIP002/SIP022 docs checked 2026-07-18",
        "mihomo": "MetaCubeX/mihomo v1.19.28 release/docs checked 2026-07-18",
        "sing_box": "SagerNet/sing-box stable docs/releases checked 2026-07-18",
    }
