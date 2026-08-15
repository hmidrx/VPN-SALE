from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.delivery import (
    DeliveryError,
    DeliveryOutputFormat,
    DeliveryProtocol,
    issue_subscription_token,
    render_qr_png,
)

from platform_api.activation_models import ServiceDeliveryModel
from platform_api.config import Settings, get_settings
from platform_api.customer_auth.routes import current_customer_session_dependency
from platform_api.database import get_db_session
from platform_api.identity.models import CustomerSessionModel
from platform_api.identity.security import EncryptedSecret, FernetSecretEncryptor, SecretEncryptionError
from platform_api.service_models import ServiceAttachmentModel, ServiceModel

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


def _verified_required_attachments(db: Session, service_id: str) -> bool:
    attachments = list(
        db.scalars(
            select(ServiceAttachmentModel).where(
                ServiceAttachmentModel.service_id == service_id,
                ServiceAttachmentModel.required.is_(True),
            )
        )
    )
    return bool(attachments) and all(
        item.status == "VERIFIED" and item.verification_status == "VERIFIED"
        for item in attachments
    )


def _decrypt_delivery(
    delivery: ServiceDeliveryModel,
    settings: Settings,
) -> tuple[str, ...]:
    if delivery.encryption_key_version != settings.identity_encryption_key_version:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_KEY_VERSION_UNAVAILABLE"},
        )
    if not settings.identity_encryption_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_KEY_UNAVAILABLE"},
        )
    try:
        plaintext = FernetSecretEncryptor(
            settings.identity_encryption_key,
            settings.identity_encryption_key_version,
        ).decrypt(EncryptedSecret(delivery.encryption_key_version, delivery.encrypted_payload))
    except SecretEncryptionError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_DECRYPTION_FAILED"},
        ) from exc
    if not __import__("hmac").compare_digest(
        hashlib.sha256(plaintext.encode()).hexdigest(), delivery.payload_sha256
    ):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_INTEGRITY_FAILED"},
        )
    try:
        parsed: object = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_PAYLOAD_INVALID"},
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_PAYLOAD_INVALID"},
        )
    payload = cast(dict[str, object], parsed)
    links_value = payload.get("links")
    if payload.get("version") != 1 or not isinstance(links_value, list):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_PAYLOAD_INVALID"},
        )
    links: list[str] = []
    for raw in cast(list[object], links_value):
        if (
            not isinstance(raw, str)
            or len(raw) > 8192
            or not raw.startswith(("vless://", "vmess://"))
        ):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "DELIVERY_PAYLOAD_INVALID"},
            )
        links.append(raw)
    if not links or len(links) != delivery.item_count:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DELIVERY_PAYLOAD_INVALID"},
        )
    return tuple(links)


@customer_router.get("/services/{service_reference}", response_model=DeliverySummary)
def customer_service_delivery(
    service_reference: str,
    response: Response,
    session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
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
    delivery = db.scalar(
        select(ServiceDeliveryModel).where(ServiceDeliveryModel.service_id == service.id)
    )
    if delivery is None or delivery.status != "DELIVERED":
        return DeliverySummary(
            service_reference=service.public_reference,
            status="PENDING_DELIVERY",
            delivery_ready=False,
            connections=[],
            formats=[],
        )
    links = _decrypt_delivery(delivery, settings)
    return DeliverySummary(
        service_reference=service.public_reference,
        status="ACTIVE",
        delivery_ready=True,
        connections=[{"uri": link} for link in links],
        formats=[DeliveryOutputFormat.URI, DeliveryOutputFormat.PLAIN_LINKS],
    )


@customer_router.post(
    "/services/{service_reference}/subscription", response_model=SubscriptionStatus
)
async def issue_customer_subscription(service_reference: str) -> SubscriptionStatus:
    token, _record = issue_subscription_token(datetime.now(UTC))
    return SubscriptionStatus(
        service_reference=service_reference,
        status="ACTIVE",
        stable_urls=_stable_urls(token),
        token_visible_once=token,
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


def _stable_urls(token: str) -> dict[str, str]:
    return {
        "base64": f"/subscriptions/{token}",
        "links": f"/subscriptions/{token}/links",
        "mihomo": f"/subscriptions/{token}/mihomo",
        "clash": f"/subscriptions/{token}/clash",
        "sing_box": f"/subscriptions/{token}/sing-box",
    }


def _renderer_contracts() -> dict[str, str]:
    return {
        "xray": "Project X transport/protocol docs checked 2026-07-18",
        "shadowsocks": "SIP002/SIP022 docs checked 2026-07-18",
        "mihomo": "MetaCubeX/mihomo v1.19.28 release/docs checked 2026-07-18",
        "sing_box": "SagerNet/sing-box stable docs/releases checked 2026-07-18",
    }
