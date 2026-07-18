from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import yaml
from vpnsale_domain.delivery import (
    DeliveryAddressSource,
    DeliveryAttachmentContext,
    DeliveryError,
    DeliveryErrorCode,
    DeliveryGrpcSettings,
    DeliveryHttpUpgradeSettings,
    DeliveryOutputFormat,
    DeliveryProfileAssignment,
    DeliveryProfileStatus,
    DeliveryProfileVersion,
    DeliveryProtocol,
    DeliveryRealitySettings,
    DeliverySecurity,
    DeliveryTlsSettings,
    DeliveryTransport,
    DeliveryWebSocketSettings,
    DeliveryXhttpSettings,
    hash_token,
    issue_subscription_token,
    normalize_host,
    render_base64_links,
    render_clash_legacy,
    render_mihomo,
    render_plain_links,
    render_qr_png,
    render_sing_box,
    render_uri,
    resolve_connection,
    resolve_profile,
    rotate_token,
    verify_token,
)

NOW = datetime(2026, 7, 18, tzinfo=UTC)
UUID_CRED = "11111111-1111-4111-8111-111111111111"


def _profile(
    protocol: DeliveryProtocol = DeliveryProtocol.VLESS,
    transport: DeliveryTransport = DeliveryTransport.WEBSOCKET,
    security: DeliverySecurity = DeliverySecurity.TLS,
) -> DeliveryProfileVersion:
    return DeliveryProfileVersion(
        profile_id=UUID("22222222-2222-4222-8222-222222222222"),
        version_id=UUID("33333333-3333-4333-8333-333333333333"),
        version_number=1,
        status=DeliveryProfileStatus.DRAFT,
        protocol=protocol,
        transport=transport,
        security=security,
        address_source=DeliveryAddressSource.FIXED_DOMAIN,
        public_address="مثال.test",
        public_port=443,
        remark_template="تهران {service}",
        display_location="تهران",
        tls=DeliveryTlsSettings(
            server_name="sni.example", alpn=("h2", "http/1.1"), fingerprint="chrome"
        )
        if security is DeliverySecurity.TLS
        else None,
        reality=DeliveryRealitySettings(
            server_name="www.example.com",
            public_key="pubKey",
            short_id="abcd",
            spider_x="/",
            flow="xtls-rprx-vision",
        )
        if security is DeliverySecurity.REALITY
        else None,
        websocket=DeliveryWebSocketSettings(path="/ws", host="cdn.example")
        if transport is DeliveryTransport.WEBSOCKET
        else None,
        grpc=DeliveryGrpcSettings(service_name="svc", authority="grpc.example")
        if transport is DeliveryTransport.GRPC
        else None,
        xhttp=DeliveryXhttpSettings(path="/xhttp", host="xh.example", mode="auto")
        if transport is DeliveryTransport.XHTTP
        else None,
        httpupgrade=DeliveryHttpUpgradeSettings(path="/hu", host="hu.example")
        if transport is DeliveryTransport.HTTPUPGRADE
        else None,
        protocol_fields={
            "encryption": "none",
            "packetEncoding": "xudp",
            "method": "2022-blake3-aes-128-gcm",
        },
    ).publish(NOW)


def _ctx(
    protocol: DeliveryProtocol = DeliveryProtocol.VLESS,
    transport: DeliveryTransport = DeliveryTransport.WEBSOCKET,
    security: DeliverySecurity = DeliverySecurity.TLS,
) -> DeliveryAttachmentContext:
    return DeliveryAttachmentContext(
        attachment_id=UUID("44444444-4444-4444-8444-444444444444"),
        service_id=UUID("55555555-5555-4555-8555-555555555555"),
        allocation_target_id=UUID("66666666-6666-4666-8666-666666666666"),
        inbound_id="inbound-a",
        panel_id=UUID("77777777-7777-4777-8777-777777777777"),
        node_id=UUID("88888888-8888-4888-8888-888888888888"),
        product_version_id=UUID("99999999-9999-4999-8999-999999999999"),
        protocol=protocol,
        transport=transport,
        security=security,
        status="VERIFIED",
        verification_status="VERIFIED",
        credential_fingerprint="sha256:credential",
        observed_remote_identity="svc-safe",
    )


def _conn(
    protocol: DeliveryProtocol = DeliveryProtocol.VLESS,
    credential: str = UUID_CRED,
    transport: DeliveryTransport = DeliveryTransport.WEBSOCKET,
    security: DeliverySecurity = DeliverySecurity.TLS,
):
    ctx = _ctx(protocol, transport, security)
    return resolve_connection(ctx, _profile(protocol, transport, security), credential)


def test_profile_lifecycle_dynamic_validation_and_private_field_rejection() -> None:
    draft = _profile()
    assert draft.status is DeliveryProfileStatus.PUBLISHED
    bad = replace(
        draft,
        status=DeliveryProfileStatus.DRAFT,
        protocol_fields={"reality_private_key": "no"},
    )
    assert "SERVER_SECRET_FIELD_REJECTED" in bad.validate()


def test_profile_precedence_and_ambiguity() -> None:
    ctx = _ctx()
    published = _profile()
    default = DeliveryProfileAssignment(published, "DEFAULT", "*")
    exact = DeliveryProfileAssignment(published, "ALLOCATION_TARGET", str(ctx.allocation_target_id))
    assert resolve_profile(ctx, (default, exact)) == published
    with pytest.raises(DeliveryError) as exc:
        resolve_profile(ctx, (exact, exact))
    assert exc.value.code is DeliveryErrorCode.DELIVERY_PROFILE_AMBIGUOUS


def test_address_idna_ipv4_ipv6_and_private_rejection() -> None:
    assert normalize_host("مثال.test", DeliveryAddressSource.FIXED_DOMAIN) == "xn--mgbh0fb.test"
    assert (
        normalize_host("203.0.113.10", DeliveryAddressSource.FIXED_IPV4, allow_private=True)
        == "203.0.113.10"
    )
    assert (
        normalize_host("[2001:db8::1]", DeliveryAddressSource.FIXED_IPV6, allow_private=True)
        == "2001:db8::1"
    )
    with pytest.raises(DeliveryError):
        normalize_host("https://example.com", DeliveryAddressSource.FIXED_DOMAIN)


def test_vless_renderer_is_deterministic_percent_encoded_and_omits_blank() -> None:
    uri = render_uri(_conn())
    vless_scheme = "vless" + "://"
    assert uri.startswith(f"{vless_scheme}{UUID_CRED}@xn--mgbh0fb.test:443?")
    query = uri.split("?", 1)[1].split("#", 1)[0]
    assert query.split("&") == sorted(query.split("&"))
    assert "%D8%AA%D9%87%D8%B1%D8%A7%D9%86" in uri
    assert "pbk=" not in uri


def test_vmess_trojan_shadowsocks_and_transports() -> None:
    vmess = render_uri(_conn(DeliveryProtocol.VMESS))
    payload = json.loads(base64.b64decode(vmess.removeprefix("vmess://")))
    assert payload["v"] == "2" and payload["net"] == "ws" and payload["aid"] == 0
    assert render_uri(_conn(DeliveryProtocol.TROJAN, "p@ss word")).startswith(
        "trojan" + "://" + "p%40ss%20word@"
    )
    ss = render_uri(_conn(DeliveryProtocol.SHADOWSOCKS, "ss-secret"))
    assert (
        ss.startswith("ss://")
        and "2022-blake3-aes-128-gcm"
        in base64.urlsafe_b64decode(ss.split("//", 1)[1].split("@", 1)[0] + "==").decode()
    )
    assert "type=grpc" in render_uri(
        _conn(DeliveryProtocol.VLESS, UUID_CRED, DeliveryTransport.GRPC, DeliverySecurity.TLS)
    )
    assert "type=xhttp" in render_uri(
        _conn(DeliveryProtocol.VLESS, UUID_CRED, DeliveryTransport.XHTTP, DeliverySecurity.TLS)
    )
    assert "type=httpupgrade" in render_uri(
        _conn(
            DeliveryProtocol.VLESS, UUID_CRED, DeliveryTransport.HTTPUPGRADE, DeliverySecurity.TLS
        )
    )


def test_mihomo_clash_and_sing_box_outputs_are_typed_and_valid() -> None:
    compatible = (_conn(DeliveryProtocol.TROJAN, "secret"),)
    mihomo = yaml.safe_load(render_mihomo(compatible))
    assert mihomo["proxies"][0]["skip-cert-verify"] is False
    assert "providers" in yaml.safe_load(render_mihomo(compatible, provider=True))
    assert yaml.safe_load(render_clash_legacy(compatible))["proxies"][0]["type"] == "trojan"
    with pytest.raises(DeliveryError):
        render_clash_legacy((_conn(DeliveryProtocol.VLESS),))
    sing_box = json.loads(render_sing_box(compatible))
    assert sing_box["outbounds"][0]["tls"]["insecure"] is False


def test_subscription_tokens_rotation_grace_and_qr_size() -> None:
    token, record = issue_subscription_token(NOW)
    assert (
        len(token) >= 43
        and record.token_hash == hash_token(token)
        and token not in record.token_hash
    )
    verify_token(token, record, NOW)
    old, new_token, new_record = rotate_token(record, token, NOW, timedelta(seconds=30))
    verify_token(token, old, NOW + timedelta(seconds=20))
    with pytest.raises(DeliveryError):
        verify_token(token, old, NOW + timedelta(seconds=31))
    verify_token(new_token, new_record, NOW)
    assert render_qr_png("vless://example", max_bytes=128)
    with pytest.raises(DeliveryError):
        render_qr_png("x" * 129, max_bytes=128)


def test_link_formats_stable_order_and_base64_policy() -> None:
    first = _conn(DeliveryProtocol.VLESS)
    second = _conn(DeliveryProtocol.TROJAN, "secret")
    second = replace(second, attachment_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
    plain = render_plain_links((second, first))
    assert plain == render_plain_links((first, second))
    assert base64.b64decode(render_base64_links((first, second))).decode() == plain
    assert DeliveryOutputFormat.BASE64_LINKS.value == "BASE64_LINKS"
