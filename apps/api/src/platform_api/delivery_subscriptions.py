from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.delivery import (
    DeliveryAttachmentContext,
    DeliveryError,
    DeliveryErrorCode,
    DeliveryOutputFormat,
    DeliveryProfileStatus,
    DeliveryResolvedConnection,
    DeliverySubscriptionToken,
    DeliveryProtocol,
    hash_token,
    issue_subscription_token,
    render_base64_links,
    render_clash_legacy,
    render_mihomo,
    render_plain_links,
    render_sing_box,
    resolve_connection,
    verify_token,
)

from platform_api.delivery_models import (
    DeliveryAccessEventModel,
    DeliveryProfileVersionModel,
    DeliveryRevisionModel,
    DeliverySubscriptionModel,
    DeliverySubscriptionTokenModel,
)
from platform_api.delivery_resolution import RENDERER_VERSION, delivery_profile_from_model
from platform_api.service_models import AllocationTargetModel, ServiceAttachmentModel, ServiceModel

SERVICE_SCOPE = "SERVICE"
ROTATION_GRACE = timedelta(minutes=5)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
TokenStatus = Literal["ACTIVE", "ROTATING", "REVOKED", "EXPIRED"]


@dataclass(frozen=True)
class SubscriptionMutationResult:
    public_reference: str
    status: str
    token: str | None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _lock_service(db: Session, service_id: str) -> ServiceModel:
    service = db.get(ServiceModel, service_id, with_for_update=True)
    if service is None:
        raise DeliveryError(DeliveryErrorCode.DELIVERY_NOT_READY, "service unavailable")
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


def active_revision_connection(db: Session, service: ServiceModel) -> DeliveryResolvedConnection:
    if service.lifecycle != "ACTIVE":
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_SERVICE_INACTIVE,
            "service is not active",
        )
    attachments = _required_attachments(db, service.id)
    if len(attachments) != 1:
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_NOT_READY,
            "delivery attachment cardinality invalid",
        )
    attachment = attachments[0]
    if attachment.status != "VERIFIED" or attachment.verification_status != "VERIFIED":
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_ATTACHMENT_UNVERIFIED,
            "delivery attachment is not verified",
        )
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
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_REVISION_STALE,
            "active delivery revision missing",
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
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_REVISION_STALE,
            "delivery revision no longer matches the service",
        )
    if revision.renderer_versions.get("URI") != RENDERER_VERSION:
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_REVISION_STALE,
            "delivery renderer version unavailable",
        )
    if revision.compatibility_state.get("provider_host_used") is not False:
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_REVISION_STALE,
            "delivery revision is unsafe",
        )
    target = db.get(AllocationTargetModel, target_id)
    profile_row = db.get(DeliveryProfileVersionModel, profile_version_id)
    if target is None or profile_row is None:
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_REVISION_STALE,
            "delivery revision references unavailable state",
        )
    profile = delivery_profile_from_model(profile_row, require_published=False)
    remote_identity = attachment.remote_identity_reference
    if not remote_identity:
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_CREDENTIAL_UNAVAILABLE,
            "remote identity unavailable",
        )
    product_version = service.entitlement_snapshot.get("product_version_id")
    if not isinstance(product_version, str) or not product_version:
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_FIELD_REQUIRED,
            "product version unavailable",
        )
    fingerprint = hashlib.sha256(remote_identity.encode()).hexdigest()
    expected_fingerprint = revision.credential_fingerprints.get(attachment.id)
    if not isinstance(expected_fingerprint, str) or not hmac.compare_digest(
        expected_fingerprint, fingerprint
    ):
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_REVISION_STALE,
            "delivery credential fingerprint changed",
        )
    if not hmac.compare_digest(profile_version_id, str(profile.version_id)):
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_REVISION_STALE,
            "delivery profile version changed",
        )
    ctx = DeliveryAttachmentContext(
        attachment_id=UUID(attachment.id),
        service_id=UUID(service.id),
        allocation_target_id=UUID(target.id),
        inbound_id=target.inbound_id,
        panel_id=UUID(target.panel_id),
        node_id=UUID(target.node_id) if target.node_id else None,
        product_version_id=UUID(product_version),
        protocol=DeliveryProtocol(target.required_protocol.upper()),
        transport=profile.transport,
        security=profile.security,
        status=attachment.status,
        verification_status=attachment.verification_status,
        credential_fingerprint=fingerprint,
        observed_remote_identity=remote_identity,
        required=attachment.required,
    )
    resolution_profile = profile
    if profile.status is DeliveryProfileStatus.SUPERSEDED:
        resolution_profile = replace(profile, status=DeliveryProfileStatus.PUBLISHED)
    return resolve_connection(ctx, resolution_profile, remote_identity)


def _subscription_for_update(db: Session, service_id: str) -> DeliverySubscriptionModel | None:
    return db.scalar(
        select(DeliverySubscriptionModel)
        .where(
            DeliverySubscriptionModel.service_id == service_id,
            DeliverySubscriptionModel.scope == SERVICE_SCOPE,
        )
        .with_for_update()
    )


def _token_for_update(db: Session, token_hash_value: str) -> DeliverySubscriptionTokenModel | None:
    return db.scalar(
        select(DeliverySubscriptionTokenModel)
        .where(DeliverySubscriptionTokenModel.token_hash == token_hash_value)
        .with_for_update()
    )


def _record_event(
    db: Session,
    *,
    subscription_id: str | None,
    service_id: str | None,
    actor_type: str,
    action: str,
    outcome: str,
    now: datetime,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        DeliveryAccessEventModel(
            subscription_id=subscription_id,
            service_id=service_id,
            actor_type=actor_type,
            action=action,
            outcome=outcome,
            safe_metadata=metadata or {},
            created_at=now,
        )
    )


def issue_service_subscription(
    db: Session,
    service_id: str,
    now: datetime,
) -> SubscriptionMutationResult:
    now = _aware(now)
    service = _lock_service(db, service_id)
    active_revision_connection(db, service)
    subscription = _subscription_for_update(db, service.id)
    if subscription is not None and subscription.status == "ACTIVE":
        if not subscription.active_token_hash:
            raise DeliveryError(
                DeliveryErrorCode.SERVICE_UNAVAILABLE,
                "active subscription has no active token",
            )
        active = _token_for_update(db, subscription.active_token_hash)
        if active is None or active.status != "ACTIVE":
            raise DeliveryError(
                DeliveryErrorCode.SERVICE_UNAVAILABLE,
                "active subscription token state is inconsistent",
            )
        return SubscriptionMutationResult(subscription.public_reference, "ACTIVE", None)

    token, record = issue_subscription_token(now)
    if subscription is None:
        subscription = DeliverySubscriptionModel(
            public_reference=f"sub_{uuid4().hex}",
            service_id=service.id,
            scope=SERVICE_SCOPE,
            status="ACTIVE",
            active_token_hash=record.token_hash,
            created_at=now,
            updated_at=now,
        )
        db.add(subscription)
        db.flush()
    else:
        subscription.status = "ACTIVE"
        subscription.active_token_hash = record.token_hash
        subscription.updated_at = now
    db.add(
        DeliverySubscriptionTokenModel(
            subscription_id=subscription.id,
            token_hash=record.token_hash,
            status=record.status,
            issued_at=record.issued_at,
            grace_expires_at=record.grace_expires_at,
            revoked_at=None,
        )
    )
    _record_event(
        db,
        subscription_id=subscription.id,
        service_id=service.id,
        actor_type="CUSTOMER",
        action="SUBSCRIPTION_ISSUED",
        outcome="SUCCESS",
        now=now,
        metadata={"scope": SERVICE_SCOPE},
    )
    db.flush()
    return SubscriptionMutationResult(subscription.public_reference, "ACTIVE", token)


def rotate_service_subscription(
    db: Session,
    service_id: str,
    now: datetime,
) -> SubscriptionMutationResult:
    now = _aware(now)
    service = _lock_service(db, service_id)
    active_revision_connection(db, service)
    subscription = _subscription_for_update(db, service.id)
    if subscription is None or subscription.status != "ACTIVE" or not subscription.active_token_hash:
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_NOT_FOUND, "subscription unavailable")
    rotating = db.scalar(
        select(DeliverySubscriptionTokenModel)
        .where(
            DeliverySubscriptionTokenModel.subscription_id == subscription.id,
            DeliverySubscriptionTokenModel.status == "ROTATING",
        )
        .order_by(DeliverySubscriptionTokenModel.issued_at.desc())
        .limit(1)
        .with_for_update()
    )
    if (
        rotating is not None
        and rotating.grace_expires_at is not None
        and _aware(rotating.grace_expires_at) > now
    ):
        raise DeliveryError(
            DeliveryErrorCode.IDEMPOTENCY_CONFLICT,
            "subscription rotation already in progress",
        )
    active = _token_for_update(db, subscription.active_token_hash)
    if active is None or active.status != "ACTIVE":
        raise DeliveryError(
            DeliveryErrorCode.SERVICE_UNAVAILABLE,
            "active subscription token state is inconsistent",
        )
    new_token, new_record = issue_subscription_token(now)
    active.status = "ROTATING"
    active.grace_expires_at = now + ROTATION_GRACE
    subscription.active_token_hash = new_record.token_hash
    subscription.updated_at = now
    db.add(
        DeliverySubscriptionTokenModel(
            subscription_id=subscription.id,
            token_hash=new_record.token_hash,
            status="ACTIVE",
            issued_at=new_record.issued_at,
            grace_expires_at=None,
            revoked_at=None,
        )
    )
    _record_event(
        db,
        subscription_id=subscription.id,
        service_id=service.id,
        actor_type="CUSTOMER",
        action="SUBSCRIPTION_ROTATED",
        outcome="SUCCESS",
        now=now,
        metadata={"grace_seconds": int(ROTATION_GRACE.total_seconds())},
    )
    db.flush()
    return SubscriptionMutationResult(subscription.public_reference, "ACTIVE", new_token)


def revoke_service_subscription(
    db: Session,
    service_id: str,
    now: datetime,
) -> SubscriptionMutationResult:
    now = _aware(now)
    service = _lock_service(db, service_id)
    subscription = _subscription_for_update(db, service.id)
    if subscription is None:
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_NOT_FOUND, "subscription unavailable")
    if subscription.status == "REVOKED":
        return SubscriptionMutationResult(subscription.public_reference, "REVOKED", None)
    tokens = list(
        db.scalars(
            select(DeliverySubscriptionTokenModel)
            .where(
                DeliverySubscriptionTokenModel.subscription_id == subscription.id,
                DeliverySubscriptionTokenModel.status.in_(("ACTIVE", "ROTATING")),
            )
            .with_for_update()
        )
    )
    for token in tokens:
        token.status = "REVOKED"
        token.revoked_at = now
        token.grace_expires_at = None
    subscription.status = "REVOKED"
    subscription.active_token_hash = None
    subscription.updated_at = now
    _record_event(
        db,
        subscription_id=subscription.id,
        service_id=service.id,
        actor_type="CUSTOMER",
        action="SUBSCRIPTION_REVOKED",
        outcome="SUCCESS",
        now=now,
    )
    db.flush()
    return SubscriptionMutationResult(subscription.public_reference, "REVOKED", None)


def _domain_token(row: DeliverySubscriptionTokenModel) -> DeliverySubscriptionToken:
    if row.status not in {"ACTIVE", "ROTATING", "REVOKED", "EXPIRED"}:
        raise DeliveryError(DeliveryErrorCode.SERVICE_UNAVAILABLE, "subscription state invalid")
    return DeliverySubscriptionToken(
        token_hash=row.token_hash,
        status=cast(TokenStatus, row.status),
        issued_at=_aware(row.issued_at),
        grace_expires_at=_aware(row.grace_expires_at) if row.grace_expires_at else None,
    )


def _render_output(
    connection: DeliveryResolvedConnection,
    fmt: DeliveryOutputFormat,
) -> str:
    connections = (connection,)
    if fmt is DeliveryOutputFormat.PLAIN_LINKS:
        return render_plain_links(connections)
    if fmt is DeliveryOutputFormat.BASE64_LINKS:
        return render_base64_links(connections)
    if fmt is DeliveryOutputFormat.MIHOMO:
        return render_mihomo(connections)
    if fmt is DeliveryOutputFormat.CLASH_LEGACY:
        return render_clash_legacy(connections)
    if fmt is DeliveryOutputFormat.SING_BOX:
        return render_sing_box(connections)
    raise DeliveryError(
        DeliveryErrorCode.SUBSCRIPTION_FORMAT_UNSUPPORTED,
        "subscription format unavailable",
    )


def render_public_subscription(
    db: Session,
    opaque_token: str,
    fmt: DeliveryOutputFormat,
    now: datetime,
) -> str:
    now = _aware(now)
    if not _TOKEN_RE.fullmatch(opaque_token):
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_NOT_FOUND, "subscription unavailable")
    presented_hash = hash_token(opaque_token)
    token_row = db.scalar(
        select(DeliverySubscriptionTokenModel).where(
            DeliverySubscriptionTokenModel.token_hash == presented_hash
        )
    )
    if token_row is None:
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_NOT_FOUND, "subscription unavailable")
    verify_token(opaque_token, _domain_token(token_row), now)
    subscription = db.get(DeliverySubscriptionModel, token_row.subscription_id)
    if subscription is None or subscription.status != "ACTIVE":
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_REVOKED, "subscription unavailable")
    if token_row.status == "ACTIVE" and (
        subscription.active_token_hash is None
        or not hmac.compare_digest(subscription.active_token_hash, token_row.token_hash)
    ):
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_REVOKED, "subscription unavailable")
    service = db.get(ServiceModel, subscription.service_id)
    if service is None:
        raise DeliveryError(DeliveryErrorCode.DELIVERY_NOT_READY, "service unavailable")
    connection = active_revision_connection(db, service)
    try:
        rendered = _render_output(connection, fmt)
    except DeliveryError:
        _record_event(
            db,
            subscription_id=subscription.id,
            service_id=service.id,
            actor_type="SUBSCRIPTION_TOKEN",
            action="SUBSCRIPTION_RENDER",
            outcome="REJECTED",
            now=now,
            metadata={"format": fmt.value},
        )
        raise
    _record_event(
        db,
        subscription_id=subscription.id,
        service_id=service.id,
        actor_type="SUBSCRIPTION_TOKEN",
        action="SUBSCRIPTION_RENDER",
        outcome="SUCCESS",
        now=now,
        metadata={"format": fmt.value},
    )
    return rendered
