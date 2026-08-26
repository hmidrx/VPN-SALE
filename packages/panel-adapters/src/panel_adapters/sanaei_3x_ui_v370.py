"""Exact Sanaei/3x-ui v3.7.0 global-client management contract.

This is the production adapter for the certified official v3.7.0 tag. It models
only routes and fields verified in that source snapshot and leaves retry, TLS,
endpoint-origin validation and write enablement to the injectable transport and
the application-level safety gates. The v3.5.0 modules remain isolated legacy
compatibility code and are never composed by the v3.7.0 workers.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast
from urllib.parse import quote, unquote

import httpx
from vpnsale_domain.providers import (
    ProviderContractVersion,
    ProviderError,
    ProviderErrorCode,
    ProviderKind,
)

from panel_adapters.contracts import VERSIONED_CERTIFIED_CONTRACTS, SanitizedHttpResponse


class Sanaei3xUiV370Authentication(StrEnum):
    """Authentication mechanisms accepted by the tagged management API."""

    BEARER_TOKEN = "bearer_token"  # noqa: S105 -- public auth-mode identifier
    SESSION_COOKIE = "session_cookie"  # noqa: S105 -- public auth-mode identifier


class Sanaei3xUiV370Operation(StrEnum):
    SERVER_STATUS = "server.status"
    INBOUND_OPTIONS = "inbounds.options"
    CLIENT_ADD = "clients.add"
    CLIENT_READ = "clients.get"
    CLIENT_UPDATE = "clients.update"
    CLIENT_DELETE = "clients.delete"
    CLIENT_ATTACH = "clients.attach"
    CLIENT_DETACH = "clients.detach"
    CLIENT_RESET_TRAFFIC = "clients.resetTraffic"
    CLIENT_CLEAR_IPS = "clients.clearIps"
    CLIENT_LINKS = "clients.links"
    CLIENT_SUB_LINKS = "clients.subLinks"


@dataclass(frozen=True)
class Sanaei3xUiV370CapabilityEnvelope:
    """Version and privilege facts a caller must check before enabling this client."""

    contract: ProviderContractVersion
    authentication_preference: tuple[Sanaei3xUiV370Authentication, ...]
    required_bearer_scope: str
    operations: frozenset[Sanaei3xUiV370Operation]
    total_gb_unit: str
    expiry_time_unit: str
    writes_enabled_by_default: bool


SANAEI_3X_UI_V370_CONTRACT = VERSIONED_CERTIFIED_CONTRACTS[(ProviderKind.SANAEI_3X_UI, "v3.7.0")]

SANAEI_3X_UI_V370_CAPABILITIES = Sanaei3xUiV370CapabilityEnvelope(
    contract=SANAEI_3X_UI_V370_CONTRACT,
    authentication_preference=(
        Sanaei3xUiV370Authentication.BEARER_TOKEN,
        Sanaei3xUiV370Authentication.SESSION_COOKIE,
    ),
    # The complete add -> readback -> delivery flow needs routes which are not in
    # the v3.7.0 monitor or node-sync allowlists.
    required_bearer_scope="admin",
    operations=frozenset(Sanaei3xUiV370Operation),
    total_gb_unit="bytes",
    expiry_time_unit="unix_milliseconds",
    writes_enabled_by_default=False,
)


class Sanaei3xUiV370Transport(Protocol):
    """Minimal injectable HTTP surface.

    A cookie-authenticated implementation must retain cookies between calls made on
    the same transport instance. Implementations also own TLS policy, bounded
    timeouts, response-size limits, redaction and safe retry behavior.
    """

    async def get(
        self, path: str, headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse: ...

    async def post_json(
        self,
        path: str,
        payload: Mapping[str, object],
        headers: dict[str, str] | None = None,
    ) -> SanitizedHttpResponse: ...


class HttpxSanaei3xUiV370Transport:
    """Bounded no-redirect transport for a previously validated panel origin.

    Session credentials are exchanged for an HTTP-only panel cookie through the
    release's public CSRF endpoint. Bearer credentials never enter a cookie jar.
    Response headers and bodies are reduced to the sanitized adapter contract.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        authorization_header: str | None,
        session_csrf_token: str | None,
        max_response_bytes: int,
    ) -> None:
        self._client = client
        self._authorization_header = authorization_header
        self._session_csrf_token = session_csrf_token  # noqa: S105 -- runtime secret reference
        self._max_response_bytes = max_response_bytes

    @property
    def bearer_authenticated(self) -> bool:
        return self._authorization_header is not None

    @property
    def session_csrf_token(self) -> str | None:
        """Opaque CSRF value paired with this transport's authenticated cookie jar."""

        return self._session_csrf_token

    @classmethod
    async def connect(
        cls,
        endpoint_origin: str,
        *,
        base_path: str = "",
        bearer_token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        two_factor_code: str = "",
        verify_tls: bool = True,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2_000_000,
    ) -> HttpxSanaei3xUiV370Transport:
        if max_response_bytes < 16_384:
            raise ValueError("max response size is too small")
        has_bearer = bearer_token is not None
        has_session = username is not None or password is not None
        if has_bearer == has_session:
            raise ValueError("exactly one provider authentication mode is required")
        client = httpx.AsyncClient(
            base_url=endpoint_origin.rstrip("/"),
            verify=verify_tls,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )
        if has_bearer:
            token = _required_string(bearer_token, "bearer_token")  # noqa: S105
            if token != token.strip() or "\r" in token or "\n" in token:
                await client.aclose()
                raise ValueError("bearer token is invalid")
            return cls(
                client,
                authorization_header=f"Bearer {token}",
                session_csrf_token=None,
                max_response_bytes=max_response_bytes,
            )
        try:
            normalized_base = normalize_sanaei_base_path(base_path)
            csrf_response = await client.get(f"{normalized_base}/csrf-token")
            csrf_body = cls._bounded_json(csrf_response, max_response_bytes)
            if csrf_response.status_code != 200 or not isinstance(csrf_body, Mapping):
                raise PermissionError("provider CSRF negotiation failed")
            csrf_mapping = cast(Mapping[str, object], csrf_body)
            if csrf_mapping.get("success") is not True or not isinstance(
                csrf_mapping.get("obj"), str
            ):
                raise PermissionError("provider CSRF negotiation failed")
            csrf_token = cast(str, csrf_mapping["obj"])
            login_response = await client.post(
                f"{normalized_base}/login",
                data={
                    "username": _required_string(username, "username"),
                    "password": _required_string(password, "password"),
                    "twoFactorCode": two_factor_code,
                },
                headers={"X-CSRF-Token": csrf_token, "Accept": "application/json"},
            )
            login_body = cls._bounded_json(login_response, max_response_bytes)
            if login_response.status_code != 200 or not isinstance(login_body, Mapping):
                raise PermissionError("provider authentication failed")
            login_mapping = cast(Mapping[str, object], login_body)
            if login_mapping.get("success") is not True:
                raise PermissionError("provider authentication failed")
        except (httpx.HTTPError, ValueError, PermissionError):
            await client.aclose()
            raise
        return cls(
            client,
            authorization_header=None,
            session_csrf_token=csrf_token,
            max_response_bytes=max_response_bytes,
        )

    @staticmethod
    def _bounded_json(response: httpx.Response, max_response_bytes: int) -> object | None:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > max_response_bytes:
                    raise ProviderError(
                        ProviderErrorCode.PROVIDER_RESPONSE_TOO_LARGE,
                        "provider response exceeded the configured limit",
                    )
            except ValueError:
                pass
        if len(response.content) > max_response_bytes:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_TOO_LARGE,
                "provider response exceeded the configured limit",
            )
        try:
            return response.json()
        except ValueError:
            return None

    def _headers(self, supplied: dict[str, str] | None) -> dict[str, str] | None:
        headers = dict(supplied or {})
        if self._authorization_header is not None:
            headers["Authorization"] = self._authorization_header
        return headers or None

    def _sanitized(self, response: httpx.Response, started: float) -> SanitizedHttpResponse:
        body = self._bounded_json(response, self._max_response_bytes)
        return SanitizedHttpResponse(
            response.status_code,
            body,
            {},
            max(0, int((time.monotonic() - started) * 1000)),
        )

    async def get(self, path: str, headers: dict[str, str] | None = None) -> SanitizedHttpResponse:
        started = time.monotonic()
        response = await self._client.get(path, headers=self._headers(headers))
        return self._sanitized(response, started)

    async def post_json(
        self,
        path: str,
        payload: Mapping[str, object],
        headers: dict[str, str] | None = None,
    ) -> SanitizedHttpResponse:
        started = time.monotonic()
        response = await self._client.post(path, json=dict(payload), headers=self._headers(headers))
        return self._sanitized(response, started)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpxSanaei3xUiV370Transport:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()


def normalize_sanaei_base_path(raw_base_path: str) -> str:
    """Return an empty prefix or one canonical, traversal-free path prefix."""

    value = raw_base_path.strip()
    if value in {"", "/"}:
        return ""
    if (
        "://" in value
        or value.startswith("//")
        or "?" in value
        or "#" in value
        or "\\" in value
        or "%" in value
        or any(ord(character) < 32 for character in value)
        or any(character.isspace() for character in value)
    ):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED,
            "panel base path is invalid",
        )
    parts = tuple(part for part in value.split("/") if part)
    decoded_parts = tuple(unquote(part) for part in parts)
    if not parts or any(
        part in {".", ".."} or "/" in part or "\\" in part for part in decoded_parts
    ):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED,
            "panel base path is invalid",
        )
    return "/" + "/".join(parts)


def unix_milliseconds(value: datetime | None) -> int:
    """Convert an aware timestamp to the integer millisecond unit used by 3x-ui."""

    if value is None:
        return 0
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("expiry must be timezone-aware")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value.astimezone(UTC) - epoch
    milliseconds = delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000
    if milliseconds < 0:
        raise ValueError("expiry cannot precede the Unix epoch")
    return milliseconds


def sanaei_client_limit_fields(*, total_bytes: int, expiry_at: datetime | None) -> dict[str, int]:
    """Build the two unit-sensitive upstream fields without GB/second conversion."""

    if type(total_bytes) is not int or total_bytes < 0:
        raise ValueError("total_bytes must be a non-negative integer")
    return {"totalGB": total_bytes, "expiryTime": unix_milliseconds(expiry_at)}


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _required_path_identifier(value: object, field: str) -> str:
    identifier = _required_string(value, field)
    if (
        identifier != identifier.strip()
        or len(identifier) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in identifier)
        or any(character in "/\\?#" for character in identifier)
    ):
        raise ValueError(f"{field} is invalid")
    return identifier


def _opaque_secret(value: object, field: str) -> str:
    secret = _required_string(value, field)
    if secret != secret.strip() or "\r" in secret or "\n" in secret:
        raise ValueError(f"{field} is invalid")
    return secret


def _non_negative_integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _inbound_ids(values: Sequence[int], *, require_one: bool = True) -> tuple[int, ...]:
    normalized: list[int] = []
    for value in values:
        if type(value) is not int or value <= 0:
            raise ValueError("inboundIds must contain positive integers")
        if value not in normalized:
            normalized.append(value)
    if require_one and not normalized:
        raise ValueError("at least one inboundId is required")
    return tuple(normalized)


@dataclass(frozen=True)
class Sanaei3xUiV370CreateRequest:
    """Verified v3.7.0 `ClientCreatePayload` (`client` plus `inboundIds`)."""

    client: Mapping[str, object]
    inbound_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        copied_client = dict(self.client)
        _required_path_identifier(copied_client.get("email"), "client.email")
        _non_negative_integer(copied_client.get("totalGB"), "client.totalGB")
        _non_negative_integer(copied_client.get("expiryTime"), "client.expiryTime")
        object.__setattr__(self, "client", copied_client)
        object.__setattr__(self, "inbound_ids", _inbound_ids(self.inbound_ids))

    @property
    def email(self) -> str:
        return cast(str, self.client["email"])

    @property
    def total_bytes(self) -> int:
        return cast(int, self.client["totalGB"])

    @property
    def expiry_time_ms(self) -> int:
        return cast(int, self.client["expiryTime"])

    def as_payload(self) -> dict[str, object]:
        return {"client": dict(self.client), "inboundIds": list(self.inbound_ids)}


@dataclass(frozen=True)
class Sanaei3xUiV370ClientRecord:
    client: Mapping[str, object]
    inbound_ids: tuple[int, ...]
    external_links: tuple[object, ...]
    used_traffic_bytes: int | None
    tunnel_allowed_ips: tuple[str, ...]

    @property
    def email(self) -> str:
        return cast(str, self.client["email"])

    @property
    def total_bytes(self) -> int:
        return cast(int, self.client["totalGB"])

    @property
    def expiry_time_ms(self) -> int:
        return cast(int, self.client["expiryTime"])

    @property
    def subscription_id(self) -> str | None:
        value = self.client.get("subId")
        if value is None:
            return None
        try:
            return _required_path_identifier(value, "client.subId")
        except ValueError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                "provider client readback shape is invalid",
            ) from exc


@dataclass(frozen=True)
class Sanaei3xUiV370InboundOption:
    """Small, validated inbound projection used by plan/attachment pickers."""

    inbound_id: int
    remark: str
    tag: str
    protocol: str
    port: int
    enabled: bool
    node_id: int | None
    tls_flow_capable: bool


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            f"provider {field} shape is invalid",
        )
    return cast(Sequence[object], value)


def _response_inbound_ids(value: object) -> tuple[int, ...]:
    try:
        return _inbound_ids(cast(Sequence[int], _sequence(value, "inboundIds")), require_one=False)
    except ValueError as exc:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            "provider inboundIds shape is invalid",
        ) from exc


def _optional_string_sequence(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    result: list[str] = []
    for index, item in enumerate(_sequence(value, field)):
        try:
            parsed = _required_string(item, f"{field}[{index}]")
        except ValueError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                f"provider {field} shape is invalid",
            ) from exc
        if "\r" in parsed or "\n" in parsed:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                f"provider {field} shape is invalid",
            )
        result.append(parsed)
    return tuple(result)


def _required_string_sequence(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            f"provider {field} shape is invalid",
        )
    return _optional_string_sequence(value, field)


def _inbound_option(value: object, index: int) -> Sanaei3xUiV370InboundOption:
    field = f"inboundOptions[{index}]"
    if not isinstance(value, Mapping):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            f"provider {field} shape is invalid",
        )
    option = cast(Mapping[str, object], value)
    try:
        inbound_id = _non_negative_integer(option.get("id"), f"{field}.id")
        port = _non_negative_integer(option.get("port"), f"{field}.port")
        if inbound_id == 0 or port > 65_535:
            raise ValueError
        remark = _required_string(option.get("remark"), f"{field}.remark")
        tag = _required_string(option.get("tag"), f"{field}.tag")
        protocol = _required_string(option.get("protocol"), f"{field}.protocol")
        enabled_value = option.get("enable")
        flow_value = option.get("tlsFlowCapable")
        if type(enabled_value) is not bool or type(flow_value) is not bool:
            raise ValueError
        node_value = option.get("nodeId")
        node_id = (
            None if node_value is None else _non_negative_integer(node_value, f"{field}.nodeId")
        )
        if node_id == 0:
            raise ValueError
    except ValueError as exc:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            f"provider {field} shape is invalid",
        ) from exc
    return Sanaei3xUiV370InboundOption(
        inbound_id=inbound_id,
        remark=remark,
        tag=tag,
        protocol=protocol,
        port=port,
        enabled=enabled_value,
        node_id=node_id,
        tls_flow_capable=flow_value,
    )


def _inbound_options(value: object) -> tuple[Sanaei3xUiV370InboundOption, ...]:
    sequence = _sequence(value, "inboundOptions")
    options = tuple(_inbound_option(item, index) for index, item in enumerate(sequence))
    if len({option.inbound_id for option in options}) != len(options):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            "provider inboundOptions contains duplicate ids",
        )
    return options


def _client_record(value: object, expected_email: str) -> Sanaei3xUiV370ClientRecord:
    if not isinstance(value, Mapping):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            "provider client readback shape is invalid",
        )
    obj = cast(Mapping[str, object], value)
    client_value = obj.get("client")
    if not isinstance(client_value, Mapping):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            "provider client readback shape is invalid",
        )
    client = dict(cast(Mapping[str, object], client_value))
    try:
        email = _required_path_identifier(client.get("email"), "client.email")
        _non_negative_integer(client.get("totalGB"), "client.totalGB")
        _non_negative_integer(client.get("expiryTime"), "client.expiryTime")
        used_traffic_value = obj.get("usedTraffic")
        used_traffic = (
            None
            if used_traffic_value is None
            else _non_negative_integer(used_traffic_value, "usedTraffic")
        )
    except ValueError as exc:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            "provider client readback shape is invalid",
        ) from exc
    if email != expected_email:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            "provider client readback identity does not match",
        )
    external_value = obj.get("externalLinks")
    external_links = (
        () if external_value is None else tuple(_sequence(external_value, "externalLinks"))
    )
    return Sanaei3xUiV370ClientRecord(
        client=client,
        inbound_ids=_response_inbound_ids(obj.get("inboundIds")),
        external_links=external_links,
        used_traffic_bytes=used_traffic,
        tunnel_allowed_ips=_optional_string_sequence(
            obj.get("tunnelAllowedIPs"), "tunnelAllowedIPs"
        ),
    )


def _success_object(response: SanitizedHttpResponse, operation: str) -> object:
    if response.status_code == 401:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED,
            "provider authentication failed",
        )
    if response.status_code == 403:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_AUTHORIZATION_INSUFFICIENT,
            "provider credential lacks the required capability",
        )
    if response.status_code == 429:
        raise ProviderError(ProviderErrorCode.PROVIDER_RATE_LIMITED, "provider rate limited")
    if response.status_code in {408, 504}:
        raise ProviderError(ProviderErrorCode.PROVIDER_TIMEOUT, "provider request timed out")
    if response.status_code >= 500:
        raise ProviderError(ProviderErrorCode.SERVICE_UNAVAILABLE, "provider unavailable")
    body = response.json_body
    if not 200 <= response.status_code < 300 or not isinstance(body, Mapping):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            f"provider {operation} response is invalid",
        )
    envelope = cast(Mapping[str, object], body)
    if envelope.get("success") is not True:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
            f"provider {operation} did not return a success envelope",
        )
    return envelope.get("obj")


class Sanaei3xUiV370Client:
    """Transport-injected client for the verified v3.7.0 route subset."""

    contract = SANAEI_3X_UI_V370_CONTRACT
    capability_envelope = SANAEI_3X_UI_V370_CAPABILITIES

    def __init__(
        self,
        transport: Sanaei3xUiV370Transport,
        *,
        base_path: str = "",
        bearer_token: str | None = None,
        session_csrf_token: str | None = None,
    ) -> None:
        if bearer_token is not None:
            bearer_token = _opaque_secret(bearer_token, "bearer token")
        if session_csrf_token is not None:
            session_csrf_token = _opaque_secret(session_csrf_token, "session CSRF token")
        if bearer_token is not None and session_csrf_token is not None:
            raise ValueError("bearer and session authentication cannot be combined")
        self._transport = transport
        self._base_path = normalize_sanaei_base_path(base_path)
        self._bearer_token = bearer_token  # noqa: S105 -- runtime secret reference
        self._session_csrf_token = session_csrf_token  # noqa: S105 -- runtime secret reference

    @property
    def authentication(self) -> Sanaei3xUiV370Authentication:
        if self._bearer_token is not None:
            return Sanaei3xUiV370Authentication.BEARER_TOKEN
        return Sanaei3xUiV370Authentication.SESSION_COOKIE

    def _read_headers(self) -> dict[str, str]:
        if self._bearer_token is not None:
            return {"Authorization": f"Bearer {self._bearer_token}"}
        # Makes the panel return 401 (not its browser-oriented 404) when a cookie
        # expires, which permits safe authentication failure classification.
        return {"X-Requested-With": "XMLHttpRequest"}

    def _write_headers(self) -> dict[str, str]:
        if self._bearer_token is not None:
            return self._read_headers()
        if self._session_csrf_token is None:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "session CSRF token is required for provider mutations",
            )
        return {
            "X-CSRF-Token": self._session_csrf_token,
            "X-Requested-With": "XMLHttpRequest",
        }

    def _root_path(self, route: str) -> str:
        return f"{self._base_path}/{route}"

    def _api_path(self, group: str, route: str) -> str:
        return f"{self._base_path}/panel/api/{group}/{route}"

    def _client_path(self, route: str) -> str:
        return self._api_path("clients", route)

    @staticmethod
    def _path_identifier(value: str, field: str) -> str:
        return quote(_required_path_identifier(value, field), safe="")

    async def authenticate_session(
        self,
        *,
        username: str,
        password: str,
        two_factor_code: str = "",
    ) -> None:
        """Establish a cookie session through the tagged CSRF-protected login flow."""

        if self._bearer_token is not None:
            raise ValueError("session login is unavailable in bearer mode")
        username = _required_string(username, "username")
        password = _required_string(password, "password")
        if "\r" in username or "\n" in username:
            raise ValueError("username is invalid")
        if "\r" in two_factor_code or "\n" in two_factor_code:
            raise ValueError("two_factor_code is invalid")

        csrf_response = await self._transport.get(self._root_path("csrf-token"))
        csrf_value = _success_object(csrf_response, "csrf-token")
        try:
            csrf_token = _opaque_secret(csrf_value, "session CSRF token")
        except ValueError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                "provider csrf-token response is invalid",
            ) from exc

        login_response = await self._transport.post_json(
            self._root_path("login"),
            {
                "username": username,
                "password": password,
                "twoFactorCode": two_factor_code,
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        try:
            _success_object(login_response, "login")
        except ProviderError as exc:
            if exc.code in {
                ProviderErrorCode.PROVIDER_RATE_LIMITED,
                ProviderErrorCode.PROVIDER_TIMEOUT,
                ProviderErrorCode.SERVICE_UNAVAILABLE,
            }:
                raise
            raise ProviderError(
                ProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED,
                "provider authentication failed",
            ) from exc
        self._session_csrf_token = csrf_token  # noqa: S105 -- runtime secret reference

    async def list_inbound_options(self) -> tuple[Sanaei3xUiV370InboundOption, ...]:
        response = await self._transport.get(
            self._api_path("inbounds", "options"),
            headers=self._read_headers(),
        )
        return _inbound_options(_success_object(response, "inbounds.options"))

    async def server_status(self) -> Mapping[str, object]:
        response = await self._transport.get(
            self._api_path("server", "status"),
            headers=self._read_headers(),
        )
        value = _success_object(response, "server.status")
        if not isinstance(value, Mapping):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                "provider server.status shape is invalid",
            )
        return cast(Mapping[str, object], value)

    async def read_client(self, email: str) -> Sanaei3xUiV370ClientRecord:
        encoded = self._path_identifier(email, "email")
        response = await self._transport.get(
            self._client_path(f"get/{encoded}"), headers=self._read_headers()
        )
        return _client_record(_success_object(response, "clients.get"), email)

    async def add_client(self, request: Sanaei3xUiV370CreateRequest) -> Sanaei3xUiV370ClientRecord:
        response = await self._transport.post_json(
            self._client_path("add"), request.as_payload(), headers=self._write_headers()
        )
        _success_object(response, "clients.add")
        # The tagged create controller does not promise a canonical client object.
        return await self.read_client(request.email)

    async def update_client(
        self,
        email: str,
        client: Mapping[str, object],
        *,
        inbound_ids: Sequence[int] | None = None,
    ) -> Sanaei3xUiV370ClientRecord:
        """Update the tagged global-client record and verify the authoritative readback."""

        encoded = self._path_identifier(email, "email")
        payload = dict(client)
        expected_email = _required_path_identifier(payload.get("email"), "client.email")
        _non_negative_integer(payload.get("totalGB"), "client.totalGB")
        _non_negative_integer(payload.get("expiryTime"), "client.expiryTime")
        suffix = ""
        normalized: tuple[int, ...] | None = None
        if inbound_ids is not None:
            normalized = _inbound_ids(inbound_ids)
            suffix = "?inboundIds=" + ",".join(str(value) for value in normalized)
        response = await self._transport.post_json(
            self._client_path(f"update/{encoded}") + suffix,
            payload,
            headers=self._write_headers(),
        )
        _success_object(response, "clients.update")
        record = await self.read_client(expected_email)
        if normalized is not None and not set(normalized).issubset(record.inbound_ids):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                "provider update inbound postcondition was not verified",
            )
        for field in ("totalGB", "expiryTime", "enable", "limitIp"):
            if field in payload and record.client.get(field) != payload[field]:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                    "provider update postcondition was not verified",
                )
        return record

    async def delete_client(self, email: str, *, keep_traffic: bool = False) -> None:
        encoded = self._path_identifier(email, "email")
        suffix = "?keepTraffic=1" if keep_traffic else ""
        response = await self._transport.post_json(
            self._client_path(f"del/{encoded}") + suffix,
            {},
            headers=self._write_headers(),
        )
        _success_object(response, "clients.delete")

    async def reset_client_traffic(self, email: str) -> None:
        encoded = self._path_identifier(email, "email")
        response = await self._transport.post_json(
            self._client_path(f"resetTraffic/{encoded}"),
            {},
            headers=self._write_headers(),
        )
        _success_object(response, "clients.resetTraffic")

    async def clear_client_ips(self, email: str) -> None:
        encoded = self._path_identifier(email, "email")
        response = await self._transport.post_json(
            self._client_path(f"clearIps/{encoded}"),
            {},
            headers=self._write_headers(),
        )
        _success_object(response, "clients.clearIps")

    async def attach_client(
        self, email: str, inbound_ids: Sequence[int]
    ) -> Sanaei3xUiV370ClientRecord:
        normalized = _inbound_ids(inbound_ids)
        encoded = self._path_identifier(email, "email")
        response = await self._transport.post_json(
            self._client_path(f"{encoded}/attach"),
            {"inboundIds": list(normalized)},
            headers=self._write_headers(),
        )
        _success_object(response, "clients.attach")
        record = await self.read_client(email)
        if not set(normalized).issubset(record.inbound_ids):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                "provider attach postcondition was not verified",
            )
        return record

    async def detach_client(
        self, email: str, inbound_ids: Sequence[int]
    ) -> Sanaei3xUiV370ClientRecord:
        normalized = _inbound_ids(inbound_ids)
        encoded = self._path_identifier(email, "email")
        response = await self._transport.post_json(
            self._client_path(f"{encoded}/detach"),
            {"inboundIds": list(normalized)},
            headers=self._write_headers(),
        )
        _success_object(response, "clients.detach")
        record = await self.read_client(email)
        if not set(normalized).isdisjoint(record.inbound_ids):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                "provider detach postcondition was not verified",
            )
        return record

    async def client_links(self, email: str) -> tuple[str, ...]:
        encoded = self._path_identifier(email, "email")
        response = await self._transport.get(
            self._client_path(f"links/{encoded}"), headers=self._read_headers()
        )
        return _required_string_sequence(_success_object(response, "clients.links"), "links")

    async def subscription_links(self, sub_id: str) -> tuple[str, ...]:
        encoded = self._path_identifier(sub_id, "subId")
        response = await self._transport.get(
            self._client_path(f"subLinks/{encoded}"), headers=self._read_headers()
        )
        return _required_string_sequence(_success_object(response, "clients.subLinks"), "subLinks")
