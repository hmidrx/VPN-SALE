from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import zlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, cast
from urllib.parse import quote, urlencode
from uuid import UUID


class DeliveryErrorCode(StrEnum):
    DELIVERY_NOT_READY = "DELIVERY_NOT_READY"
    DELIVERY_SERVICE_INACTIVE = "DELIVERY_SERVICE_INACTIVE"
    DELIVERY_ATTACHMENT_UNVERIFIED = "DELIVERY_ATTACHMENT_UNVERIFIED"
    DELIVERY_PROFILE_NOT_FOUND = "DELIVERY_PROFILE_NOT_FOUND"
    DELIVERY_PROFILE_UNPUBLISHED = "DELIVERY_PROFILE_UNPUBLISHED"
    DELIVERY_PROFILE_AMBIGUOUS = "DELIVERY_PROFILE_AMBIGUOUS"
    DELIVERY_PROFILE_INCOMPATIBLE = "DELIVERY_PROFILE_INCOMPATIBLE"
    DELIVERY_FIELD_REQUIRED = "DELIVERY_FIELD_REQUIRED"
    DELIVERY_FIELD_INVALID = "DELIVERY_FIELD_INVALID"
    DELIVERY_ADDRESS_INVALID = "DELIVERY_ADDRESS_INVALID"
    DELIVERY_RENDERER_UNSUPPORTED = "DELIVERY_RENDERER_UNSUPPORTED"
    DELIVERY_FORMAT_UNSUPPORTED = "DELIVERY_FORMAT_UNSUPPORTED"
    DELIVERY_CREDENTIAL_UNAVAILABLE = "DELIVERY_CREDENTIAL_UNAVAILABLE"
    DELIVERY_OUTPUT_TOO_LARGE = "DELIVERY_OUTPUT_TOO_LARGE"
    DELIVERY_QR_TOO_LARGE = "DELIVERY_QR_TOO_LARGE"
    SUBSCRIPTION_NOT_FOUND = "SUBSCRIPTION_NOT_FOUND"
    SUBSCRIPTION_REVOKED = "SUBSCRIPTION_REVOKED"
    SUBSCRIPTION_EXPIRED = "SUBSCRIPTION_EXPIRED"
    SUBSCRIPTION_RATE_LIMITED = "SUBSCRIPTION_RATE_LIMITED"
    SUBSCRIPTION_FORMAT_UNSUPPORTED = "SUBSCRIPTION_FORMAT_UNSUPPORTED"
    DELIVERY_REVISION_STALE = "DELIVERY_REVISION_STALE"
    DELIVERY_ACCESS_FORBIDDEN = "DELIVERY_ACCESS_FORBIDDEN"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass(frozen=True)
class DeliveryError(ValueError):
    code: DeliveryErrorCode
    safe_message: str


class DeliveryProfileStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    VALIDATED = "VALIDATED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"
    ARCHIVED = "ARCHIVED"


class DeliveryAddressSource(StrEnum):
    FIXED_DOMAIN = "FIXED_DOMAIN"
    FIXED_IPV4 = "FIXED_IPV4"
    FIXED_IPV6 = "FIXED_IPV6"
    VERIFIED_NODE_PUBLIC_ADDRESS = "VERIFIED_NODE_PUBLIC_ADDRESS"
    VERIFIED_SERVICE_DOMAIN = "VERIFIED_SERVICE_DOMAIN"
    CONFIGURATION_REFERENCE = "CONFIGURATION_REFERENCE"


class DeliveryProtocol(StrEnum):
    VLESS = "VLESS"
    VMESS = "VMESS"
    TROJAN = "TROJAN"
    SHADOWSOCKS = "SHADOWSOCKS"


class DeliveryTransport(StrEnum):
    RAW = "RAW"
    WEBSOCKET = "WEBSOCKET"
    GRPC = "GRPC"
    XHTTP = "XHTTP"
    HTTPUPGRADE = "HTTPUPGRADE"


class DeliverySecurity(StrEnum):
    NONE = "NONE"
    TLS = "TLS"
    REALITY = "REALITY"


class DeliveryOutputFormat(StrEnum):
    URI = "URI"
    PLAIN_LINKS = "PLAIN_LINKS"
    BASE64_LINKS = "BASE64_LINKS"
    MIHOMO = "MIHOMO"
    MIHOMO_PROVIDER = "MIHOMO_PROVIDER"
    CLASH_LEGACY = "CLASH_LEGACY"
    SING_BOX = "SING_BOX"


@dataclass(frozen=True)
class DeliveryTlsSettings:
    server_name: str
    alpn: tuple[str, ...] = ()
    fingerprint: str | None = None
    verify_certificate: bool = True


@dataclass(frozen=True)
class DeliveryRealitySettings:
    server_name: str
    public_key: str
    short_id: str
    fingerprint: str = "chrome"
    spider_x: str | None = None
    flow: str | None = None


@dataclass(frozen=True)
class DeliveryWebSocketSettings:
    path: str
    host: str | None = None
    early_data_header_name: str | None = None
    early_data_length: int | None = None


@dataclass(frozen=True)
class DeliveryGrpcSettings:
    service_name: str
    authority: str | None = None
    multi_mode: bool = False


@dataclass(frozen=True)
class DeliveryXhttpSettings:
    path: str
    host: str | None = None
    mode: str | None = None


@dataclass(frozen=True)
class DeliveryHttpUpgradeSettings:
    path: str
    host: str | None = None


@dataclass(frozen=True)
class DeliveryRawSettings:
    header_type: str | None = None


@dataclass(frozen=True)
class DeliveryProfileVersion:
    profile_id: UUID
    version_id: UUID
    version_number: int
    status: DeliveryProfileStatus
    protocol: DeliveryProtocol
    transport: DeliveryTransport
    security: DeliverySecurity
    address_source: DeliveryAddressSource
    public_address: str
    public_port: int
    remark_template: str
    display_location: str
    tls: DeliveryTlsSettings | None = None
    reality: DeliveryRealitySettings | None = None
    websocket: DeliveryWebSocketSettings | None = None
    grpc: DeliveryGrpcSettings | None = None
    xhttp: DeliveryXhttpSettings | None = None
    httpupgrade: DeliveryHttpUpgradeSettings | None = None
    raw: DeliveryRawSettings | None = None
    protocol_fields: dict[str, str | int | bool] = field(default_factory=dict)
    compatibility_tags: frozenset[str] = frozenset()
    published_at: datetime | None = None

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        try:
            normalize_host(self.public_address, self.address_source)
        except DeliveryError as exc:
            errors.append(exc.code.value)
        if not 1 <= self.public_port <= 65535:
            errors.append(DeliveryErrorCode.DELIVERY_ADDRESS_INVALID.value)
        if self.status is DeliveryProfileStatus.PUBLISHED and self.published_at is None:
            errors.append("PUBLISHED_REQUIRES_TIMESTAMP")
        if self.security is DeliverySecurity.TLS and self.tls is None:
            errors.append("TLS_SETTINGS_REQUIRED")
        if self.security is DeliverySecurity.REALITY and self.reality is None:
            errors.append("REALITY_SETTINGS_REQUIRED")
        if self.security is DeliverySecurity.NONE and (self.tls or self.reality):
            errors.append("SECURITY_SETTINGS_NOT_ALLOWED")
        if self.tls and not self.tls.verify_certificate:
            errors.append("INSECURE_TLS_NOT_ALLOWED")
        transport_requirements = {
            DeliveryTransport.WEBSOCKET: self.websocket,
            DeliveryTransport.GRPC: self.grpc,
            DeliveryTransport.XHTTP: self.xhttp,
            DeliveryTransport.HTTPUPGRADE: self.httpupgrade,
            DeliveryTransport.RAW: self.raw or DeliveryRawSettings(),
        }
        if transport_requirements[self.transport] is None:
            errors.append(f"{self.transport.value}_SETTINGS_REQUIRED")
        if any(ch in self.remark_template for ch in "\r\n\t") or "://" in self.remark_template:
            errors.append("UNSAFE_REMARK_TEMPLATE")
        if any("private" in key.lower() or "secret" in key.lower() for key in self.protocol_fields):
            errors.append("SERVER_SECRET_FIELD_REJECTED")
        return tuple(errors)

    def publish(self, now: datetime) -> DeliveryProfileVersion:
        if now.tzinfo is None:
            raise DeliveryError(DeliveryErrorCode.DELIVERY_FIELD_INVALID, "timestamp must be UTC")
        errors = self.validate()
        if errors:
            raise DeliveryError(DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE, errors[0])
        return replace(self, status=DeliveryProfileStatus.PUBLISHED, published_at=now)


@dataclass(frozen=True)
class DeliveryProfileAssignment:
    profile_version: DeliveryProfileVersion
    target_type: Literal[
        "ATTACHMENT",
        "ALLOCATION_TARGET",
        "INBOUND",
        "PANEL_NODE",
        "PRODUCT_VERSION",
        "PROTOCOL_TRANSPORT_SECURITY",
        "DEFAULT",
    ]
    target_value: str
    active: bool = True

    def precedence(self) -> int:
        return {
            "ATTACHMENT": 1,
            "ALLOCATION_TARGET": 2,
            "INBOUND": 3,
            "PANEL_NODE": 4,
            "PRODUCT_VERSION": 5,
            "PROTOCOL_TRANSPORT_SECURITY": 6,
            "DEFAULT": 7,
        }[self.target_type]


@dataclass(frozen=True)
class DeliveryAttachmentContext:
    attachment_id: UUID
    service_id: UUID
    allocation_target_id: UUID
    inbound_id: str
    panel_id: UUID
    node_id: UUID | None
    product_version_id: UUID
    protocol: DeliveryProtocol
    transport: DeliveryTransport
    security: DeliverySecurity
    status: str
    verification_status: str
    credential_fingerprint: str
    observed_remote_identity: str
    required: bool = True


@dataclass(frozen=True)
class DeliveryResolvedConnection:
    attachment_id: UUID
    profile_version_id: UUID
    protocol: DeliveryProtocol
    transport: DeliveryTransport
    security: DeliverySecurity
    address: str
    port: int
    credential: str
    credential_fingerprint: str
    remark: str
    tls: DeliveryTlsSettings | None = None
    reality: DeliveryRealitySettings | None = None
    websocket: DeliveryWebSocketSettings | None = None
    grpc: DeliveryGrpcSettings | None = None
    xhttp: DeliveryXhttpSettings | None = None
    httpupgrade: DeliveryHttpUpgradeSettings | None = None
    raw: DeliveryRawSettings | None = None
    protocol_fields: dict[str, str | int | bool] = field(default_factory=dict)
    renderer_version: str = "delivery-uri-2026-07-18"


@dataclass(frozen=True)
class DeliverySubscriptionToken:
    token_hash: str
    status: Literal["ACTIVE", "ROTATING", "REVOKED", "EXPIRED"]
    issued_at: datetime
    grace_expires_at: datetime | None = None


def normalize_host(host: str, source: DeliveryAddressSource, allow_private: bool = False) -> str:
    if "://" in host or "@" in host or "/" in host or not host.strip():
        raise DeliveryError(DeliveryErrorCode.DELIVERY_ADDRESS_INVALID, "invalid host")
    candidate = host.strip().strip("[]")
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        ascii_host = candidate.encode("idna").decode("ascii").lower()
        if not re.fullmatch(r"[a-z0-9.-]{1,253}", ascii_host) or ".." in ascii_host:
            raise DeliveryError(
                DeliveryErrorCode.DELIVERY_ADDRESS_INVALID, "invalid hostname"
            ) from None
        return ascii_host
    if ip.is_private and not allow_private:
        raise DeliveryError(DeliveryErrorCode.DELIVERY_ADDRESS_INVALID, "private address blocked")
    if source is DeliveryAddressSource.FIXED_IPV6 and ip.version == 6:
        return ip.compressed
    if source is DeliveryAddressSource.FIXED_IPV4 and ip.version == 4:
        return ip.compressed
    if source in {
        DeliveryAddressSource.VERIFIED_NODE_PUBLIC_ADDRESS,
        DeliveryAddressSource.CONFIGURATION_REFERENCE,
    }:
        return ip.compressed
    raise DeliveryError(DeliveryErrorCode.DELIVERY_ADDRESS_INVALID, "address source mismatch")


def authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def resolve_profile(
    ctx: DeliveryAttachmentContext, assignments: tuple[DeliveryProfileAssignment, ...]
) -> DeliveryProfileVersion:
    matches: list[DeliveryProfileAssignment] = []
    for item in assignments:
        profile = item.profile_version
        if not item.active or profile.status is not DeliveryProfileStatus.PUBLISHED:
            continue
        if (profile.protocol, profile.transport, profile.security) != (
            ctx.protocol,
            ctx.transport,
            ctx.security,
        ):
            continue
        values = {
            "ATTACHMENT": str(ctx.attachment_id),
            "ALLOCATION_TARGET": str(ctx.allocation_target_id),
            "INBOUND": ctx.inbound_id,
            "PANEL_NODE": f"{ctx.panel_id}:{ctx.node_id or ''}",
            "PRODUCT_VERSION": str(ctx.product_version_id),
            "PROTOCOL_TRANSPORT_SECURITY": f"{ctx.protocol}:{ctx.transport}:{ctx.security}",
            "DEFAULT": "*",
        }
        if values[item.target_type] == item.target_value:
            matches.append(item)
    if not matches:
        raise DeliveryError(DeliveryErrorCode.DELIVERY_PROFILE_NOT_FOUND, "no profile")
    best = min(item.precedence() for item in matches)
    winners = [item for item in matches if item.precedence() == best]
    if len(winners) > 1:
        raise DeliveryError(DeliveryErrorCode.DELIVERY_PROFILE_AMBIGUOUS, "ambiguous profile")
    return winners[0].profile_version


def resolve_connection(
    ctx: DeliveryAttachmentContext, profile: DeliveryProfileVersion, credential: str
) -> DeliveryResolvedConnection:
    if ctx.status != "VERIFIED" or ctx.verification_status != "VERIFIED":
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_ATTACHMENT_UNVERIFIED, "attachment unverified"
        )
    if profile.status is not DeliveryProfileStatus.PUBLISHED:
        raise DeliveryError(DeliveryErrorCode.DELIVERY_PROFILE_UNPUBLISHED, "profile unpublished")
    if profile.validate():
        raise DeliveryError(DeliveryErrorCode.DELIVERY_PROFILE_INCOMPATIBLE, "profile invalid")
    host = normalize_host(profile.public_address, profile.address_source)
    return DeliveryResolvedConnection(
        attachment_id=ctx.attachment_id,
        profile_version_id=profile.version_id,
        protocol=ctx.protocol,
        transport=ctx.transport,
        security=ctx.security,
        address=host,
        port=profile.public_port,
        credential=credential,
        credential_fingerprint=ctx.credential_fingerprint,
        remark=profile.remark_template.replace("{service}", ctx.observed_remote_identity),
        tls=profile.tls,
        reality=profile.reality,
        websocket=profile.websocket,
        grpc=profile.grpc,
        xhttp=profile.xhttp,
        httpupgrade=profile.httpupgrade,
        raw=profile.raw,
        protocol_fields=profile.protocol_fields,
    )


def _query(params: dict[str, str]) -> str:
    return urlencode(
        [(k, v) for k, v in sorted(params.items()) if v != ""], quote_via=quote, safe="/:,"
    )


def render_vless(conn: DeliveryResolvedConnection) -> str:
    _require(
        conn.protocol is DeliveryProtocol.VLESS, DeliveryErrorCode.DELIVERY_RENDERER_UNSUPPORTED
    )
    _validate_uuid(conn.credential)
    params = _common_query(conn) | {
        "encryption": str(conn.protocol_fields.get("encryption", "none"))
    }
    for key in ("flow", "packetEncoding"):
        value = conn.protocol_fields.get(key)
        if isinstance(value, str) and value:
            params[key] = value
    return (
        f"vless://{conn.credential}@{authority(conn.address, conn.port)}"
        f"?{_query(params)}#{quote(conn.remark, safe='')}"
    )


def render_vmess(conn: DeliveryResolvedConnection) -> str:
    _require(
        conn.protocol is DeliveryProtocol.VMESS, DeliveryErrorCode.DELIVERY_RENDERER_UNSUPPORTED
    )
    _validate_uuid(conn.credential)
    payload = {
        "v": "2",
        "ps": conn.remark,
        "add": conn.address,
        "port": conn.port,
        "id": conn.credential,
        "aid": int(conn.protocol_fields.get("alterId", 0)),
        "scy": str(conn.protocol_fields.get("security", "auto")),
        "net": _transport_name(conn.transport),
        "type": "none",
        "host": _transport_host(conn) or "",
        "path": _transport_path(conn) or "",
        "tls": "tls" if conn.security is DeliverySecurity.TLS else "",
        "sni": conn.tls.server_name if conn.tls else "",
        "fp": conn.tls.fingerprint if conn.tls and conn.tls.fingerprint else "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "vmess://" + base64.b64encode(raw).decode("ascii")


def render_trojan(conn: DeliveryResolvedConnection) -> str:
    _require(
        conn.protocol is DeliveryProtocol.TROJAN, DeliveryErrorCode.DELIVERY_RENDERER_UNSUPPORTED
    )
    params = _common_query(conn)
    return (
        f"trojan://{quote(conn.credential, safe='')}@{authority(conn.address, conn.port)}"
        f"?{_query(params)}#{quote(conn.remark, safe='')}"
    )


def render_shadowsocks(conn: DeliveryResolvedConnection) -> str:
    _require(
        conn.protocol is DeliveryProtocol.SHADOWSOCKS,
        DeliveryErrorCode.DELIVERY_RENDERER_UNSUPPORTED,
    )
    method = str(conn.protocol_fields.get("method", ""))
    if not method:
        raise DeliveryError(DeliveryErrorCode.DELIVERY_FIELD_REQUIRED, "method required")
    userinfo = base64.urlsafe_b64encode(f"{method}:{conn.credential}".encode()).decode().rstrip("=")
    params: dict[str, str] = {}
    plugin = conn.protocol_fields.get("plugin")
    if plugin:
        if plugin not in {"obfs-local", "v2ray-plugin"}:
            raise DeliveryError(
                DeliveryErrorCode.DELIVERY_RENDERER_UNSUPPORTED, "plugin unsupported"
            )
        params["plugin"] = str(plugin)
    suffix = f"?{_query(params)}" if params else ""
    return (
        f"ss://{userinfo}@{authority(conn.address, conn.port)}/"
        f"{suffix}#{quote(conn.remark, safe='')}"
    )


def render_uri(conn: DeliveryResolvedConnection) -> str:
    return {
        DeliveryProtocol.VLESS: render_vless,
        DeliveryProtocol.VMESS: render_vmess,
        DeliveryProtocol.TROJAN: render_trojan,
        DeliveryProtocol.SHADOWSOCKS: render_shadowsocks,
    }[conn.protocol](conn)


def render_plain_links(conns: tuple[DeliveryResolvedConnection, ...]) -> str:
    return "\n".join(
        dict.fromkeys(
            render_uri(conn) for conn in sorted(conns, key=lambda c: str(c.attachment_id))
        )
    )


def render_base64_links(conns: tuple[DeliveryResolvedConnection, ...]) -> str:
    return base64.b64encode(render_plain_links(conns).encode()).decode("ascii")


def render_mihomo(conns: tuple[DeliveryResolvedConnection, ...], provider: bool = False) -> str:
    import yaml

    proxies = [_mihomo_proxy(conn) for conn in sorted(conns, key=lambda c: str(c.attachment_id))]
    doc = (
        {"proxies": proxies}
        if not provider
        else {"providers": {"vpnsale": {"type": "file", "proxies": proxies}}}
    )
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=True)


def render_clash_legacy(conns: tuple[DeliveryResolvedConnection, ...]) -> str:
    if any(
        conn.protocol is DeliveryProtocol.VLESS or conn.security is DeliverySecurity.REALITY
        for conn in conns
    ):
        raise DeliveryError(
            DeliveryErrorCode.DELIVERY_RENDERER_UNSUPPORTED, "legacy clash incompatible"
        )
    return render_mihomo(conns)


def render_sing_box(conns: tuple[DeliveryResolvedConnection, ...]) -> str:
    doc = {
        "outbounds": [
            _sing_box_outbound(conn) for conn in sorted(conns, key=lambda c: str(c.attachment_id))
        ]
    }
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def issue_subscription_token(now: datetime) -> tuple[str, DeliverySubscriptionToken]:
    token = secrets.token_urlsafe(48)
    return token, DeliverySubscriptionToken(hash_token(token), "ACTIVE", now)


def hash_token(token: str) -> str:
    digest = hashlib.sha256(token.encode()).hexdigest()
    return f"sha256:{digest}"


def verify_token(token: str, record: DeliverySubscriptionToken, now: datetime) -> None:
    if record.status == "REVOKED":
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_REVOKED, "subscription unavailable")
    if record.status == "EXPIRED":
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_EXPIRED, "subscription unavailable")
    if record.status == "ROTATING" and record.grace_expires_at and now > record.grace_expires_at:
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_REVOKED, "subscription unavailable")
    if not hmac.compare_digest(hash_token(token), record.token_hash):
        raise DeliveryError(DeliveryErrorCode.SUBSCRIPTION_NOT_FOUND, "subscription unavailable")


def rotate_token(
    old: DeliverySubscriptionToken, token: str, now: datetime, grace: timedelta
) -> tuple[DeliverySubscriptionToken, str, DeliverySubscriptionToken]:
    verify_token(token, old, now)
    new_token, new_record = issue_subscription_token(now)
    return replace(old, status="ROTATING", grace_expires_at=now + grace), new_token, new_record


def render_qr_png(payload: str, max_bytes: int = 2048) -> bytes:
    if len(payload.encode()) > max_bytes:
        raise DeliveryError(DeliveryErrorCode.DELIVERY_QR_TOO_LARGE, "QR payload too large")
    digest = hashlib.sha256(payload.encode()).digest()
    pixels = bytes(0 if byte % 2 else 255 for byte in (digest * 8)[:64])
    scanlines = b"".join(b"\x00" + pixels[row * 8 : (row + 1) * 8] for row in range(8))
    raw = zlib.compress(scanlines)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR", (8).to_bytes(4, "big") + (8).to_bytes(4, "big") + b"\x08\x00\x00\x00\x00"
        )
        + _png_chunk(b"IDAT", raw)
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data).to_bytes(4, "big")
    return len(data).to_bytes(4, "big") + kind + data + crc


def _common_query(conn: DeliveryResolvedConnection) -> dict[str, str]:
    params = {"security": conn.security.value.lower(), "type": _transport_name(conn.transport)}
    if conn.tls:
        params["sni"] = conn.tls.server_name
        if conn.tls.alpn:
            params["alpn"] = ",".join(conn.tls.alpn)
        if conn.tls.fingerprint:
            params["fp"] = conn.tls.fingerprint
    if conn.reality:
        params |= {
            "sni": conn.reality.server_name,
            "pbk": conn.reality.public_key,
            "sid": conn.reality.short_id,
            "fp": conn.reality.fingerprint,
        }
        if conn.reality.spider_x:
            params["spx"] = conn.reality.spider_x
        if conn.reality.flow:
            params["flow"] = conn.reality.flow
    path = _transport_path(conn)
    host = _transport_host(conn)
    if path:
        params["path"] = path
    if host:
        params["host"] = host
    if conn.grpc:
        params["serviceName"] = conn.grpc.service_name
        if conn.grpc.authority:
            params["authority"] = conn.grpc.authority
    if conn.xhttp and conn.xhttp.mode:
        params["mode"] = conn.xhttp.mode
    return params


def _transport_name(transport: DeliveryTransport) -> str:
    return {
        DeliveryTransport.RAW: "tcp",
        DeliveryTransport.WEBSOCKET: "ws",
        DeliveryTransport.GRPC: "grpc",
        DeliveryTransport.XHTTP: "xhttp",
        DeliveryTransport.HTTPUPGRADE: "httpupgrade",
    }[transport]


def _transport_path(conn: DeliveryResolvedConnection) -> str | None:
    return (
        (conn.websocket and conn.websocket.path)
        or (conn.xhttp and conn.xhttp.path)
        or (conn.httpupgrade and conn.httpupgrade.path)
    )


def _transport_host(conn: DeliveryResolvedConnection) -> str | None:
    return (
        (conn.websocket and conn.websocket.host)
        or (conn.xhttp and conn.xhttp.host)
        or (conn.httpupgrade and conn.httpupgrade.host)
        or (conn.grpc and conn.grpc.authority)
    )


def _mihomo_proxy(conn: DeliveryResolvedConnection) -> dict[str, object]:
    base: dict[str, object] = {
        "name": conn.remark,
        "server": conn.address,
        "port": conn.port,
        "type": conn.protocol.value.lower(),
        "udp": bool(conn.protocol_fields.get("udp", False)),
    }
    if conn.protocol in {DeliveryProtocol.VLESS, DeliveryProtocol.VMESS}:
        base["uuid"] = conn.credential
    elif conn.protocol is DeliveryProtocol.TROJAN:
        base["password"] = conn.credential
    else:
        base["cipher"] = str(conn.protocol_fields.get("method", ""))
        base["password"] = conn.credential
    if conn.security is DeliverySecurity.TLS:
        base["tls"] = True
        base["skip-cert-verify"] = False
        if conn.tls:
            base["servername"] = conn.tls.server_name
    if conn.security is DeliverySecurity.REALITY and conn.reality:
        base["reality-opts"] = {
            "public-key": conn.reality.public_key,
            "short-id": conn.reality.short_id,
        }
        base["servername"] = conn.reality.server_name
    base["network"] = _transport_name(conn.transport)
    return base


def _sing_box_outbound(conn: DeliveryResolvedConnection) -> dict[str, object]:
    out: dict[str, object] = {
        "tag": conn.remark,
        "type": conn.protocol.value.lower(),
        "server": conn.address,
        "server_port": conn.port,
    }
    if conn.protocol in {DeliveryProtocol.VLESS, DeliveryProtocol.VMESS}:
        out["uuid"] = conn.credential
    elif conn.protocol is DeliveryProtocol.TROJAN:
        out["password"] = conn.credential
    else:
        out["method"] = str(conn.protocol_fields.get("method", ""))
        out["password"] = conn.credential
    if conn.security is not DeliverySecurity.NONE:
        tls: dict[str, object] = {"enabled": True}
        if conn.tls:
            tls |= {
                "server_name": conn.tls.server_name,
                "insecure": False,
                "alpn": list(conn.tls.alpn),
            }
        if conn.reality:
            tls |= {
                "server_name": conn.reality.server_name,
                "reality": {
                    "enabled": True,
                    "public_key": conn.reality.public_key,
                    "short_id": conn.reality.short_id,
                },
            }
        out["tls"] = tls
    if conn.transport is not DeliveryTransport.RAW:
        out["transport"] = {"type": _transport_name(conn.transport)}
        path = _transport_path(conn)
        if path:
            cast(dict[str, object], out["transport"])["path"] = path
    return out


def _validate_uuid(value: str) -> None:
    try:
        UUID(value)
    except ValueError as exc:
        raise DeliveryError(DeliveryErrorCode.DELIVERY_FIELD_INVALID, "bad uuid") from exc


def _require(value: bool, code: DeliveryErrorCode) -> None:
    if not value:
        raise DeliveryError(code, code.value)
