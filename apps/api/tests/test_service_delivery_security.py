from __future__ import annotations

from datetime import UTC, datetime

import pytest
from vpnsale_domain.delivery import DeliveryError

from platform_api.delivery_models import DeliveryProfileVersionModel
from platform_api.delivery_resolution import (
    delivery_profile_from_model,
    render_service_connection,
)
from platform_api.service_models import AllocationTargetModel, ServiceAttachmentModel, ServiceModel

SERVICE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ATTACHMENT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TARGET_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
PANEL_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
PROFILE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
PROFILE_VERSION_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff"
PRODUCT_VERSION_ID = "11111111-1111-4111-8111-111111111111"
REMOTE_IDENTITY = "22222222-2222-4222-8222-222222222222"


def _profile(*, status: str = "PUBLISHED") -> DeliveryProfileVersionModel:
    return DeliveryProfileVersionModel(
        id=PROFILE_VERSION_ID,
        profile_id=PROFILE_ID,
        version_number=1,
        status=status,
        protocol="VLESS",
        transport="RAW",
        security="TLS",
        address_source="FIXED_DOMAIN",
        public_address="edge.example",
        public_port=443,
        display_location="NL",
        remark_template="VPN {service}",
        tls_settings={
            "server_name": "edge.example",
            "alpn": ["h2"],
            "verify_certificate": True,
        },
        reality_settings=None,
        transport_settings={},
        protocol_settings={"encryption": "none"},
        compatibility_tags=[],
        validation_errors=[],
        published_at=datetime(2026, 8, 15, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
    )


def _service() -> ServiceModel:
    return ServiceModel(
        id=SERVICE_ID,
        public_reference="svc_safe",
        lifecycle="ACTIVE",
        beneficiary_customer_id="customer-safe",
        payer_type="CUSTOMER",
        payer_reference="customer-safe",
        order_id="33333333-3333-4333-8333-333333333333",
        order_item_id="44444444-4444-4444-8444-444444444444",
        unit_index=1,
        entitlement_snapshot={"product_version_id": PRODUCT_VERSION_ID},
        allocation_policy_snapshot={},
        starts_at=datetime(2026, 8, 15, tzinfo=UTC),
        expires_at=datetime(2026, 9, 14, tzinfo=UTC),
        activated_at=datetime(2026, 8, 15, tzinfo=UTC),
        version=1,
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
    )


def _attachment() -> ServiceAttachmentModel:
    return ServiceAttachmentModel(
        id=ATTACHMENT_ID,
        service_id=SERVICE_ID,
        allocation_target_id=TARGET_ID,
        required=True,
        status="VERIFIED",
        verification_status="VERIFIED",
        provider_operation_id="55555555-5555-4555-8555-555555555555",
        remote_identity_reference=REMOTE_IDENTITY,
        credential_fingerprint=None,
        target_snapshot={},
        observed_state={},
        last_reconciled_at=datetime(2026, 8, 15, tzinfo=UTC),
        version=1,
    )


def _target() -> AllocationTargetModel:
    return AllocationTargetModel(
        id=TARGET_ID,
        panel_id=PANEL_ID,
        node_id=None,
        inbound_id="1",
        provider_kind="SANAEI_3X_UI",
        required_protocol="vless",
        role="PRIMARY",
        priority=1,
        weight=100,
        max_capacity=100,
        safety_reserve=5,
        status="ACTIVE",
        minimum_certification_status="CONTRACT_VERIFIED",
        safe_diagnostics={},
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
        updated_at=datetime(2026, 8, 15, tzinfo=UTC),
        version=1,
    )


def test_customer_uri_uses_published_public_profile_not_panel_host() -> None:
    profile = delivery_profile_from_model(_profile())
    uri, fingerprint = render_service_connection(
        _service(), _attachment(), _target(), profile
    )

    assert "edge.example:443" in uri
    assert "panel" not in uri.lower()
    assert REMOTE_IDENTITY in uri
    assert len(fingerprint) == 64


def test_unpublished_profile_fails_closed_before_customer_rendering() -> None:
    with pytest.raises(DeliveryError):
        delivery_profile_from_model(_profile(status="DRAFT"))


def test_superseded_revision_profile_can_still_render_existing_service() -> None:
    profile = delivery_profile_from_model(
        _profile(status="SUPERSEDED"),
        require_published=False,
    )
    uri, _fingerprint = render_service_connection(
        _service(), _attachment(), _target(), profile
    )
    assert "edge.example:443" in uri
