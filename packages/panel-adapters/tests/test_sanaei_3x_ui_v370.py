from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest
from panel_adapters.contracts import (
    CERTIFIED_CONTRACTS,
    VERSIONED_CERTIFIED_CONTRACTS,
    SanitizedHttpResponse,
)
from panel_adapters.sanaei_3x_ui_v370 import (
    SANAEI_3X_UI_V370_CAPABILITIES,
    Sanaei3xUiV370Authentication,
    Sanaei3xUiV370Client,
    Sanaei3xUiV370CreateRequest,
    Sanaei3xUiV370Operation,
    normalize_sanaei_base_path,
    sanaei_client_limit_fields,
    unix_milliseconds,
)
from vpnsale_domain.providers import ProviderError, ProviderErrorCode, ProviderKind

FIXTURE_ROOT = (
    Path(__file__).parents[3]
    / "docs"
    / "provider-contracts"
    / "sanaei-3x-ui"
    / "v3.7.0"
    / "fixtures"
)


def fixture(name: str) -> dict[str, object]:
    loaded = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast(dict[str, object], loaded)


class FixtureTransport:
    def __init__(
        self,
        *,
        gets: Mapping[str, SanitizedHttpResponse] | None = None,
        posts: Mapping[str, SanitizedHttpResponse] | None = None,
    ) -> None:
        self.gets = dict(gets or {})
        self.posts = dict(posts or {})
        self.get_calls: list[tuple[str, dict[str, str] | None]] = []
        self.post_calls: list[tuple[str, dict[str, object], dict[str, str] | None]] = []

    async def get(self, path: str, headers: dict[str, str] | None = None) -> SanitizedHttpResponse:
        self.get_calls.append((path, headers))
        return self.gets[path]

    async def post_json(
        self,
        path: str,
        payload: Mapping[str, object],
        headers: dict[str, str] | None = None,
    ) -> SanitizedHttpResponse:
        self.post_calls.append((path, dict(payload), headers))
        return self.posts[path]


def response(name: str, *, status: int = 200) -> SanitizedHttpResponse:
    return SanitizedHttpResponse(status, fixture(name), {}, 1)


def readback_with_inbounds(*inbound_ids: int) -> SanitizedHttpResponse:
    body = fixture("readback-response.json")
    obj = cast(dict[str, object], body["obj"])
    obj["inboundIds"] = list(inbound_ids)
    return SanitizedHttpResponse(200, body, {}, 1)


def test_v370_contract_is_versioned_without_replacing_v350() -> None:
    legacy = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    current = VERSIONED_CERTIFIED_CONTRACTS[(ProviderKind.SANAEI_3X_UI, "v3.7.0")]

    assert legacy.release_tag == "v3.5.0"
    assert current.release_tag == "v3.7.0"
    assert current.commit_sha == "f727d04f6522bb94a8fb52e8352fdcafb51c11e1"
    assert SANAEI_3X_UI_V370_CAPABILITIES.authentication_preference[0] is (
        Sanaei3xUiV370Authentication.BEARER_TOKEN
    )
    assert SANAEI_3X_UI_V370_CAPABILITIES.required_bearer_scope == "admin"
    assert SANAEI_3X_UI_V370_CAPABILITIES.writes_enabled_by_default is False
    assert SANAEI_3X_UI_V370_CAPABILITIES.operations == frozenset(Sanaei3xUiV370Operation)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("/", ""),
        ("panel", "/panel"),
        ("/tenant/panel/", "/tenant/panel"),
        ("/tenant//panel//", "/tenant/panel"),
    ],
)
def test_base_path_normalization(raw: str, expected: str) -> None:
    assert normalize_sanaei_base_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://panel.example.invalid/base",
        "/base?query=1",
        "/base#fragment",
        "/base\\child",
        "/base/../admin",
        "/base/%2e%2e/admin",
        "/base/%252e%252e/admin",
        "/base/%2fadmin",
    ],
)
def test_base_path_rejects_origin_and_traversal(raw: str) -> None:
    with pytest.raises(ProviderError) as caught:
        normalize_sanaei_base_path(raw)
    assert caught.value.code is ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED


def test_totalgb_is_bytes_and_expirytime_is_aware_unix_milliseconds() -> None:
    expiry = datetime(2027, 1, 1, tzinfo=timezone(timedelta(hours=3, minutes=30)))

    fields = sanaei_client_limit_fields(total_bytes=50 * 1024**3, expiry_at=expiry)

    assert fields == {"totalGB": 50 * 1024**3, "expiryTime": 1798749000000}
    assert unix_milliseconds(datetime(2027, 1, 1, tzinfo=UTC)) == 1798761600000
    assert unix_milliseconds(None) == 0
    with pytest.raises(ValueError, match="timezone-aware"):
        unix_milliseconds(datetime(2027, 1, 1))


@pytest.mark.asyncio
async def test_add_uses_bearer_base_path_exact_payload_and_authoritative_readback() -> None:
    add_payload = fixture("add-request.json")
    request = Sanaei3xUiV370CreateRequest(
        cast(Mapping[str, object], add_payload["client"]),
        tuple(cast(list[int], add_payload["inboundIds"])),
    )
    transport = FixtureTransport(
        gets={
            "/tenant/panel/panel/api/clients/get/fixture-client-370": response(
                "readback-response.json"
            )
        },
        posts={"/tenant/panel/panel/api/clients/add": response("success-response.json")},
    )
    client = Sanaei3xUiV370Client(
        transport,
        base_path="tenant/panel/",
        bearer_token="synthetic-bearer-value",  # noqa: S106 -- inert fixture value
    )

    record = await client.add_client(request)

    authorization = {"Authorization": "Bearer synthetic-bearer-value"}
    assert client.authentication is Sanaei3xUiV370Authentication.BEARER_TOKEN
    assert transport.post_calls == [
        (
            "/tenant/panel/panel/api/clients/add",
            add_payload,
            authorization,
        )
    ]
    assert transport.get_calls == [
        (
            "/tenant/panel/panel/api/clients/get/fixture-client-370",
            authorization,
        )
    ]
    assert request.total_bytes == 53_687_091_200
    assert request.expiry_time_ms == 1_798_761_600_000
    assert record.total_bytes == request.total_bytes
    assert record.expiry_time_ms == request.expiry_time_ms
    assert record.inbound_ids == (101, 202)


@pytest.mark.asyncio
async def test_session_fallback_sends_no_authorization_header_and_encodes_identifier() -> None:
    path = "/panel/api/clients/get/fixture%2Bclient%40example.invalid"
    body = fixture("readback-response.json")
    obj = cast(dict[str, object], body["obj"])
    remote_client = cast(dict[str, object], obj["client"])
    remote_client["email"] = "fixture+client@example.invalid"
    transport = FixtureTransport(gets={path: SanitizedHttpResponse(200, body, {}, 1)})
    client = Sanaei3xUiV370Client(transport)

    record = await client.read_client("fixture+client@example.invalid")

    assert client.authentication is Sanaei3xUiV370Authentication.SESSION_COOKIE
    assert record.email == "fixture+client@example.invalid"
    assert transport.get_calls == [(path, {"X-Requested-With": "XMLHttpRequest"})]


@pytest.mark.asyncio
async def test_session_login_mints_csrf_and_reuses_it_for_mutations() -> None:
    email = "fixture-client-370"
    csrf_path = "/tenant/csrf-token"
    login_path = "/tenant/login"
    attach_path = f"/tenant/panel/api/clients/{email}/attach"
    read_path = f"/tenant/panel/api/clients/get/{email}"
    transport = FixtureTransport(
        gets={
            csrf_path: response("csrf-response.json"),
            read_path: readback_with_inbounds(101, 202),
        },
        posts={
            login_path: response("success-response.json"),
            attach_path: response("success-response.json"),
        },
    )
    client = Sanaei3xUiV370Client(transport, base_path="/tenant")

    await client.authenticate_session(
        username="fixture-admin",
        password="inert-test-password",  # noqa: S106 -- synthetic fixture only
        two_factor_code="123456",
    )
    record = await client.attach_client(email, (202,))

    csrf_headers = {"X-CSRF-Token": "synthetic-csrf-value"}
    mutation_headers = {
        "X-CSRF-Token": "synthetic-csrf-value",
        "X-Requested-With": "XMLHttpRequest",
    }
    assert record.inbound_ids == (101, 202)
    assert transport.get_calls == [
        (csrf_path, None),
        (read_path, {"X-Requested-With": "XMLHttpRequest"}),
    ]
    assert transport.post_calls == [
        (
            login_path,
            {
                "username": "fixture-admin",
                "password": "inert-test-password",
                "twoFactorCode": "123456",
            },
            csrf_headers,
        ),
        (attach_path, {"inboundIds": [202]}, mutation_headers),
    ]


@pytest.mark.asyncio
async def test_cookie_mutation_without_csrf_fails_before_transport() -> None:
    add_payload = fixture("add-request.json")
    request = Sanaei3xUiV370CreateRequest(
        cast(Mapping[str, object], add_payload["client"]),
        tuple(cast(list[int], add_payload["inboundIds"])),
    )
    transport = FixtureTransport()
    client = Sanaei3xUiV370Client(transport)

    with pytest.raises(ProviderError) as caught:
        await client.add_client(request)

    assert caught.value.code is ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE
    assert transport.post_calls == []


@pytest.mark.asyncio
async def test_attach_and_detach_use_exact_bodies_and_verify_readback() -> None:
    email = "fixture-client-370"
    get_path = f"/panel/api/clients/get/{email}"
    attach_path = f"/panel/api/clients/{email}/attach"
    attach_transport = FixtureTransport(
        gets={get_path: readback_with_inbounds(101, 202)},
        posts={attach_path: response("success-response.json")},
    )

    attached = await Sanaei3xUiV370Client(
        attach_transport,
        session_csrf_token="synthetic-csrf-value",  # noqa: S106 -- inert fixture value
    ).attach_client(email, (202,))

    assert attached.inbound_ids == (101, 202)
    session_headers = {
        "X-CSRF-Token": "synthetic-csrf-value",
        "X-Requested-With": "XMLHttpRequest",
    }
    assert attach_transport.post_calls == [
        (attach_path, fixture("attach-request.json"), session_headers)
    ]

    detach_path = f"/panel/api/clients/{email}/detach"
    detach_transport = FixtureTransport(
        gets={get_path: readback_with_inbounds(101)},
        posts={detach_path: response("success-response.json")},
    )

    detached = await Sanaei3xUiV370Client(
        detach_transport,
        session_csrf_token="synthetic-csrf-value",  # noqa: S106 -- inert fixture value
    ).detach_client(email, (202,))

    assert detached.inbound_ids == (101,)
    assert detach_transport.post_calls == [
        (detach_path, fixture("detach-request.json"), session_headers)
    ]


@pytest.mark.asyncio
async def test_update_uses_exact_query_and_verifies_fields_and_inbounds() -> None:
    email = "fixture-client-370"
    update_path = f"/panel/api/clients/update/{email}?inboundIds=101,202"
    read_path = f"/panel/api/clients/get/{email}"
    body = fixture("readback-response.json")
    client_payload = cast(dict[str, object], cast(dict[str, object], body["obj"])["client"])
    transport = FixtureTransport(
        gets={read_path: readback_with_inbounds(101, 202)},
        posts={update_path: response("success-response.json")},
    )

    record = await Sanaei3xUiV370Client(
        transport,
        bearer_token="synthetic-bearer-value",  # noqa: S106 -- inert fixture value
    ).update_client(email, client_payload, inbound_ids=(101, 202))

    headers = {"Authorization": "Bearer synthetic-bearer-value"}
    assert record.inbound_ids == (101, 202)
    assert transport.post_calls == [(update_path, client_payload, headers)]
    assert transport.get_calls == [(read_path, headers)]


@pytest.mark.asyncio
async def test_delete_reset_and_clear_ips_use_exact_v370_routes() -> None:
    email = "fixture-client-370"
    headers = {
        "X-CSRF-Token": "synthetic-csrf-value",
        "X-Requested-With": "XMLHttpRequest",
    }
    paths = {
        f"/panel/api/clients/del/{email}?keepTraffic=1": response("success-response.json"),
        f"/panel/api/clients/resetTraffic/{email}": response("success-response.json"),
        f"/panel/api/clients/clearIps/{email}": response("success-response.json"),
    }
    transport = FixtureTransport(posts=paths)
    client = Sanaei3xUiV370Client(
        transport,
        session_csrf_token="synthetic-csrf-value",  # noqa: S106 -- inert fixture value
    )

    await client.delete_client(email, keep_traffic=True)
    await client.reset_client_traffic(email)
    await client.clear_client_ips(email)

    assert transport.post_calls == [(path, {}, headers) for path in paths]


@pytest.mark.asyncio
async def test_detach_can_authoritatively_read_back_an_orphan_client() -> None:
    email = "fixture-client-370"
    get_path = f"/panel/api/clients/get/{email}"
    detach_path = f"/panel/api/clients/{email}/detach"
    transport = FixtureTransport(
        gets={get_path: readback_with_inbounds()},
        posts={detach_path: response("success-response.json")},
    )

    record = await Sanaei3xUiV370Client(
        transport,
        session_csrf_token="synthetic-csrf-value",  # noqa: S106 -- inert fixture value
    ).detach_client(email, (101,))

    assert record.inbound_ids == ()


@pytest.mark.asyncio
async def test_links_and_sublinks_use_distinct_exact_routes() -> None:
    transport = FixtureTransport(
        gets={
            "/base/panel/api/clients/links/fixture-client-370": response("links-response.json"),
            "/base/panel/api/clients/subLinks/fixture-sub-id-370": response(
                "sub-links-response.json"
            ),
        }
    )
    client = Sanaei3xUiV370Client(transport, base_path="/base/")

    links = await client.client_links("fixture-client-370")
    sub_links = await client.subscription_links("fixture-sub-id-370")

    assert links == (
        "synthetic-config://fixture-one",
        "synthetic-config://fixture-two",
    )
    assert sub_links == (
        "synthetic-config://fixture-sub-one",
        "synthetic-config://fixture-sub-two",
    )


@pytest.mark.asyncio
async def test_inbound_options_are_typed_for_multi_inbound_selection() -> None:
    path = "/panel/api/inbounds/options"
    transport = FixtureTransport(gets={path: response("inbound-options-response.json")})
    client = Sanaei3xUiV370Client(
        transport,
        bearer_token="synthetic-bearer-value",  # noqa: S106 -- inert fixture value
    )

    options = await client.list_inbound_options()

    assert tuple(option.inbound_id for option in options) == (101, 202)
    assert options[0].protocol == "vless"
    assert options[0].tls_flow_capable is True
    assert options[1].node_id == 7
    assert options[1].enabled is False
    assert transport.get_calls == [(path, {"Authorization": "Bearer synthetic-bearer-value"})]


@pytest.mark.asyncio
async def test_inbound_options_reject_duplicate_remote_ids() -> None:
    path = "/panel/api/inbounds/options"
    body = fixture("inbound-options-response.json")
    options = cast(list[dict[str, object]], body["obj"])
    options[1]["id"] = 101
    client = Sanaei3xUiV370Client(
        FixtureTransport(gets={path: SanitizedHttpResponse(200, body, {}, 1)})
    )

    with pytest.raises(ProviderError) as caught:
        await client.list_inbound_options()

    assert caught.value.code is ProviderErrorCode.PROVIDER_RESPONSE_INVALID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_value", "expected_code"),
    [
        (
            SanitizedHttpResponse(200, {"success": False, "obj": []}, {}, 1),
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
        ),
        (
            SanitizedHttpResponse(200, {"success": 1, "obj": []}, {}, 1),
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
        ),
        (
            SanitizedHttpResponse(200, ["not-an-envelope"], {}, 1),
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
        ),
        (
            SanitizedHttpResponse(403, {"success": False}, {}, 1),
            ProviderErrorCode.PROVIDER_AUTHORIZATION_INSUFFICIENT,
        ),
    ],
)
async def test_http_and_literal_success_envelope_are_both_required(
    response_value: SanitizedHttpResponse,
    expected_code: ProviderErrorCode,
) -> None:
    path = "/panel/api/clients/links/fixture-client-370"
    client = Sanaei3xUiV370Client(FixtureTransport(gets={path: response_value}))

    with pytest.raises(ProviderError) as caught:
        await client.client_links("fixture-client-370")

    assert caught.value.code is expected_code


@pytest.mark.asyncio
async def test_success_envelope_still_requires_operation_specific_object_shape() -> None:
    path = "/panel/api/clients/links/fixture-client-370"
    client = Sanaei3xUiV370Client(
        FixtureTransport(
            gets={
                path: SanitizedHttpResponse(
                    200,
                    {"success": True, "obj": {"unexpected": "mapping"}},
                    {},
                    1,
                )
            }
        )
    )

    with pytest.raises(ProviderError) as caught:
        await client.client_links("fixture-client-370")

    assert caught.value.code is ProviderErrorCode.PROVIDER_RESPONSE_INVALID
