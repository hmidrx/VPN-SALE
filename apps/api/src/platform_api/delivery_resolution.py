from __future__ import annotations

import hashlib
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.delivery import (
    DeliveryAddressSource,
    DeliveryAttachmentContext,
    DeliveryError,
    DeliveryErrorCode,
    DeliveryGrpcSettings,
    DeliveryHttpUpgradeSettings,
    DeliveryProfileStatus,
    DeliveryProfileVersion,
    DeliveryProtocol,
    DeliveryRawSettings,
    DeliveryRealitySettings,
    DeliverySecurity,
    DeliveryTlsSettings,
    DeliveryTransport,
    DeliveryWebSocketSettings,
    DeliveryXhttpSettings,
    render_vless,
    render_vmess,
    resolve_connection,
)

from platform_api.delivery_models import (
    DeliveryProfileAssignmentModel,
    DeliveryProfileVersionModel,
)
from platform_api.service_models import AllocationTargetModel, ServiceAttachmentModel, ServiceModel

RENDERER_VERSION = "delivery-uri-2026-07-18"


def _str_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, object], value)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if type(value) is int else None


def delivery_profile_from_model(
    row: DeliveryProfileVersionModel,
    *,
    require_published: bool = True,
) -> DeliveryProfileVersion:
    tls_value = _str_dict(row.tls_settings)
    reality_value = _str_dict(row.reality_settings)
    transport_value = _str_dict(row.transport_settings)
    protocol_value = _str_dict(row.protocol_settings)

    tls = None
    if tls_value:
        server_name = tls_value.get("server_name")
        alpn_raw = tls_value.get("alpn", [])
        if not isinstance(alpn_raw, list):
            raise DeliveryError(
                DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE,
                "invalid TLS profile",
            )
        alpn_objects = cast(list[object], alpn_raw)
        if not isinstance(server_name, str) or not all(
            isinstance(item, str) for item in alpn_objects
        ):
            raise DeliveryError(
                DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE,
                "invalid TLS profile",
            )
        tls = DeliveryTlsSettings(
            server_name=server_name,
            alpn=tuple(cast(list[str], alpn_objects)),
            fingerprint=_optional_str(tls_value.get("fingerprint")),
            verify_certificate=tls_value.get("verify_certificate") is not False,
        )

    reality = None
    if reality_value:
        server_name = reality_value.get("server_name")
        public_key = reality_value.get("public_key")
        short_id = reality_value.get("short_id")
        if not all(
            isinstance(value, str) and value for value in (server_name, public_key, short_id)
        ):
            raise DeliveryError(
                DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE,
                "invalid REALITY profile",
            )
        reality = DeliveryRealitySettings(
            server_name=cast(str, server_name),
            public_key=cast(str, public_key),
            short_id=cast(str, short_id),
            fingerprint=_optional_str(reality_value.get("fingerprint")) or "chrome",
            spider_x=_optional_str(reality_value.get("spider_x")),
            flow=_optional_str(reality_value.get("flow")),
        )

    transport = DeliveryTransport(row.transport)
    websocket = None
    grpc = None
    xhttp = None
    httpupgrade = None
    raw = None
    if transport is DeliveryTransport.WEBSOCKET:
        path = transport_value.get("path")
        if not isinstance(path, str) or not path:
            raise DeliveryError(
                DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE,
                "invalid WebSocket profile",
            )
        websocket = DeliveryWebSocketSettings(
            path=path,
            host=_optional_str(transport_value.get("host")),
            early_data_header_name=_optional_str(transport_value.get("early_data_header_name")),
            early_data_length=_optional_int(transport_value.get("early_data_length")),
        )
    elif transport is DeliveryTransport.GRPC:
        service_name = transport_value.get("service_name")
        if not isinstance(service_name, str) or not service_name:
            raise DeliveryError(
                DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE,
                "invalid gRPC profile",
            )
        grpc = DeliveryGrpcSettings(
            service_name=service_name,
            authority=_optional_str(transport_value.get("authority")),
            multi_mode=transport_value.get("multi_mode") is True,
        )
    elif transport is DeliveryTransport.XHTTP:
        path = transport_value.get("path")
        if not isinstance(path, str) or not path:
            raise DeliveryError(
                DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE,
                "invalid XHTTP profile",
            )
        xhttp = DeliveryXhttpSettings(
            path=path,
            host=_optional_str(transport_value.get("host")),
            mode=_optional_str(transport_value.get("mode")),
        )
    elif transport is DeliveryTransport.HTTPUPGRADE:
        path = transport_value.get("path")
        if not isinstance(path, str) or not path:
            raise DeliveryError(
                DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE,
                "invalid HTTPUpgrade profile",
            )
        httpupgrade = DeliveryHttpUpgradeSettings(
            path=path,
            host=_optional_str(transport_value.get("host")),
        )
    elif transport is DeliveryTransport.RAW:
        raw = DeliveryRawSettings(header_type=_optional_str(transport_value.get("header_type")))

    protocol_fields: dict[str, str | int | bool] = {}
    for key, value in protocol_value.items():
        if isinstance(value, str) or isinstance(value, bool):
            protocol_fields[key] = value
        elif type(value) is int:
            protocol_fields[key] = value

    profile = DeliveryProfileVersion(
        profile_id=UUID(row.profile_id),
        version_id=UUID(row.id),
        version_number=row.version_number,
        status=DeliveryProfileStatus(row.status),
        protocol=DeliveryProtocol(row.protocol),
        transport=transport,
        security=DeliverySecurity(row.security),
        address_source=DeliveryAddressSource(row.address_source),
        public_address=row.public_address,
        public_port=row.public_port,
        remark_template=row.remark_template,
        display_location=row.display_location,
        tls=tls,
        reality=reality,
        websocket=websocket,
        grpc=grpc,
        xhttp=xhttp,
        httpupgrade=httpupgrade,
        raw=raw,
        protocol_fields=protocol_fields,
        compatibility_tags=frozenset(row.compatibility_tags or []),
        published_at=row.published_at,
    )
    allowed_statuses = {DeliveryProfileStatus.PUBLISHED}
    if not require_published:
        allowed_statuses.add(DeliveryProfileStatus.SUPERSEDED)
    if profile.status not in allowed_statuses or profile.published_at is None or profile.validate():
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE,
            "delivery profile is not renderable",
        )
    return profile


def load_allocation_delivery_profile(
    db: Session,
    allocation_target_id: str,
    required_protocol: str,
) -> DeliveryProfileVersion:
    assignment = db.scalar(
        select(DeliveryProfileAssignmentModel).where(
            DeliveryProfileAssignmentModel.target_type == "ALLOCATION_TARGET",
            DeliveryProfileAssignmentModel.target_value == allocation_target_id,
            DeliveryProfileAssignmentModel.active.is_(True),
        )
    )
    if assignment is None:
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_PROFILE_NOT_FOUND,
            "allocation target has no published delivery profile",
        )
    row = db.get(DeliveryProfileVersionModel, assignment.profile_version_id)
    if row is None:
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_PROFILE_NOT_FOUND,
            "delivery profile version missing",
        )
    profile = delivery_profile_from_model(row)
    if profile.protocol.value.lower() != required_protocol.lower():
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE,
            "delivery profile protocol does not match allocation target",
        )
    return profile


def render_service_connection(
    service: ServiceModel,
    attachment: ServiceAttachmentModel,
    target: AllocationTargetModel,
    profile: DeliveryProfileVersion,
    *,
    require_verified: bool = True,
) -> tuple[str, str]:
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
        status="VERIFIED" if require_verified else attachment.status,
        verification_status=("VERIFIED" if require_verified else attachment.verification_status),
        credential_fingerprint=fingerprint,
        observed_remote_identity=remote_identity,
        required=attachment.required,
    )
    connection = resolve_connection(ctx, profile, remote_identity)
    if connection.protocol is DeliveryProtocol.VLESS:
        rendered = render_vless(connection)
    elif connection.protocol is DeliveryProtocol.VMESS:
        rendered = render_vmess(connection)
    else:
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_RENDERER_UNSUPPORTED,
            "activation delivery supports VLESS/VMess only",
        )
    return rendered, fingerprint
