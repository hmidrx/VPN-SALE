"""Authenticated administration of certified VPN panel instances.

Provider credentials are accepted only through the write endpoint, encrypted before
they enter the database and never returned by any read model.  Live calls and
inventory synchronization are deliberately separated from metadata management so a
bad panel cannot make the control-plane CRUD surface unavailable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from panel_adapters.contracts import VERSIONED_CERTIFIED_CONTRACTS, EndpointValidator
from panel_adapters.sanaei_3x_ui_v370 import (
    SANAEI_3X_UI_V370_CAPABILITIES,
    HttpxSanaei3xUiV370Transport,
    Sanaei3xUiV370Client,
    normalize_sanaei_base_path,
)
from panel_adapters.vault import EncryptedProviderCredential, ProviderCredentialVault
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from vpnsale_domain.identity import sanitize_metadata
from vpnsale_domain.providers import (
    PanelEndpointPolicy,
    PanelTlsPolicy,
    ProviderError,
    ProviderErrorCode,
    ProviderKind,
)

from .database import get_db_session
from .identity.models import AdminModel, AuditLogModel
from .management import require_perm
from .provider_runtime_models import (
    PanelCredentialModel,
    PanelInstanceModel,
    ProviderConnectionTestModel,
    ProviderInboundSnapshotModel,
    ProviderSyncRunModel,
)

router = APIRouter(prefix="/api/v1/admin/providers", tags=["admin-providers"])

PanelStatus = Literal["DRAFT", "ACTIVE", "DISABLED", "RECERTIFICATION_REQUIRED"]
CredentialKind = Literal["bearer_token", "username_password"]


class TlsPolicyInput(BaseModel):
    verify_tls: bool = True
    ca_certificate_reference: str | None = Field(default=None, max_length=160)
    certificate_fingerprint_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class EndpointPolicyInput(BaseModel):
    allow_private_network: bool = False
    allowed_ports: list[int] = Field(
        default_factory=lambda: [443, 8443], min_length=1, max_length=8
    )
    require_https: bool = True
    max_response_bytes: int = Field(default=2_000_000, ge=16_384, le=8_000_000)


class PanelCreateRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=160)
    provider_kind: ProviderKind = ProviderKind.SANAEI_3X_UI
    provider_version: str = Field(default="v3.7.0", max_length=32)
    endpoint_origin: str = Field(min_length=8, max_length=512)
    base_path: str = Field(default="", max_length=160)
    tls_policy: TlsPolicyInput = Field(default_factory=TlsPolicyInput)
    endpoint_policy: EndpointPolicyInput = Field(default_factory=EndpointPolicyInput)


class PanelUpdateRequest(BaseModel):
    optimistic_version: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=2, max_length=160)
    status: PanelStatus | None = None
    endpoint_origin: str | None = Field(default=None, min_length=8, max_length=512)
    base_path: str | None = Field(default=None, max_length=160)
    tls_policy: TlsPolicyInput | None = None
    endpoint_policy: EndpointPolicyInput | None = None


class CredentialWriteRequest(BaseModel):
    auth_mode: CredentialKind
    bearer_token: SecretStr | None = Field(  # noqa: S105 -- typed secret input, no literal
        default=None, min_length=8, max_length=8192
    )
    username: str | None = Field(default=None, min_length=1, max_length=160)
    password: SecretStr | None = Field(  # noqa: S105 -- typed secret input, no literal
        default=None, min_length=1, max_length=8192
    )


class CredentialSummary(BaseModel):
    configured: bool
    credential_kind: str | None = None
    key_version: str | None = None
    updated_at: datetime | None = None


class ConnectionSummary(BaseModel):
    status: str
    detected_version: str | None = None
    contract_digest: str | None = None
    latency_ms: int | None = None
    safe_error_code: str | None = None
    tested_at: datetime


class PanelResponse(BaseModel):
    id: str
    public_reference: str
    display_name: str
    provider_kind: str
    provider_version: str
    endpoint_origin: str
    base_path: str
    status: str
    tls_policy: dict[str, object]
    endpoint_policy: dict[str, object]
    optimistic_version: int
    credential: CredentialSummary
    last_connection_test: ConnectionSummary | None
    created_at: datetime
    updated_at: datetime


class PanelListResponse(BaseModel):
    items: list[PanelResponse]


class CapabilityResponse(BaseModel):
    provider_kind: str
    provider_version: str
    contract_digest: str
    release_commit: str
    authentication_preference: list[str]
    required_bearer_scope: str
    operations: list[str]
    writes_enabled_by_default: bool


class InboundSnapshotResponse(BaseModel):
    remote_identifier: str
    status: str | None
    sanitized_payload: dict[str, object]
    observed_at: datetime
    sync_reference: str | None


class SyncResponse(BaseModel):
    sync_reference: str
    status: str
    inbound_count: int
    detected_version: str | None
    safe_error_code: str | None = None
    completed_at: datetime


def _safe_error(code: str, http_status: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(http_status, detail={"code": code})


def _audit(
    db: Session,
    admin: AdminModel,
    request: Request,
    event_code: str,
    panel_id: str,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLogModel(
            actor_type="admin",
            actor_id=admin.id,
            target_type="panel_instance",
            target_id=panel_id,
            event_code=event_code,
            occurred_at=datetime.now(UTC),
            correlation_id=(
                request.headers.get("x-request-id")
                or request.headers.get("x-correlation-id")
                or "local"
            ),
            metadata_=sanitize_metadata(metadata or {}),
        )
    )


def _tls(value: TlsPolicyInput) -> PanelTlsPolicy:
    return PanelTlsPolicy(
        verify_tls=value.verify_tls,
        ca_certificate_reference=value.ca_certificate_reference,
        certificate_fingerprint_sha256=(
            value.certificate_fingerprint_sha256.lower()
            if value.certificate_fingerprint_sha256
            else None
        ),
    )


def _endpoint(value: EndpointPolicyInput) -> PanelEndpointPolicy:
    if len(set(value.allowed_ports)) != len(value.allowed_ports):
        raise _safe_error("PROVIDER_ENDPOINT_PORTS_DUPLICATED")
    if any(port < 1 or port > 65535 for port in value.allowed_ports):
        raise _safe_error("PROVIDER_ENDPOINT_PORT_INVALID")
    return PanelEndpointPolicy(
        allow_private_network=value.allow_private_network,
        allowed_ports=frozenset(value.allowed_ports),
        require_https=value.require_https,
        max_response_bytes=value.max_response_bytes,
    )


def _validated_location(
    endpoint_origin: str,
    base_path: str,
    tls_input: TlsPolicyInput,
    endpoint_input: EndpointPolicyInput,
) -> tuple[str, str]:
    parsed = urlsplit(endpoint_origin.strip())
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise _safe_error("PROVIDER_ORIGIN_MUST_NOT_CONTAIN_PATH")
    normalized_base_path = normalize_sanaei_base_path(base_path)
    tls = _tls(tls_input)
    endpoint = _endpoint(endpoint_input)
    try:
        validated = EndpointValidator().validate(endpoint_origin.strip(), endpoint, tls)
    except (ProviderError, OSError, ValueError) as exc:
        raise _safe_error("PROVIDER_ENDPOINT_REJECTED") from exc
    origin = urlsplit(validated)
    return f"{origin.scheme}://{origin.hostname}:{origin.port}", normalized_base_path


def _panel(db: Session, public_reference: str) -> PanelInstanceModel:
    row = db.scalar(
        select(PanelInstanceModel).where(PanelInstanceModel.public_reference == public_reference)
    )
    if row is None:
        raise _safe_error("PROVIDER_PANEL_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    return row


def _credential(db: Session, panel_id: str) -> PanelCredentialModel | None:
    return db.scalar(
        select(PanelCredentialModel)
        .where(PanelCredentialModel.panel_instance_id == panel_id)
        .order_by(PanelCredentialModel.created_at.desc())
        .limit(1)
    )


def _last_test(db: Session, panel_id: str) -> ProviderConnectionTestModel | None:
    return db.scalar(
        select(ProviderConnectionTestModel)
        .where(ProviderConnectionTestModel.panel_instance_id == panel_id)
        .order_by(ProviderConnectionTestModel.tested_at.desc())
        .limit(1)
    )


def _provider_version(row: PanelInstanceModel) -> str:
    configured = row.endpoint_policy.get("provider_version")
    return configured if isinstance(configured, str) else "v3.7.0"


def _connection_failure_code(exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return exc.code.value
    if isinstance(exc, PermissionError):
        return "PROVIDER_AUTHENTICATION_FAILED"
    if isinstance(exc, httpx.TimeoutException):
        return "PROVIDER_TIMEOUT"
    if isinstance(exc, httpx.HTTPError | OSError):
        return "PROVIDER_UNREACHABLE"
    return "PROVIDER_RESPONSE_INVALID"


async def _live_client(
    db: Session, row: PanelInstanceModel
) -> tuple[HttpxSanaei3xUiV370Transport, Sanaei3xUiV370Client]:
    credential = _credential(db, row.id)
    if credential is None:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
            "provider credential is not configured",
        )
    if row.tls_policy.get("ca_certificate_reference") or row.tls_policy.get(
        "certificate_fingerprint_sha256"
    ):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_TLS_VERIFICATION_FAILED,
            "custom provider TLS material needs a configured transport resolver",
        )
    endpoint_input = EndpointPolicyInput.model_validate(
        {key: value for key, value in row.endpoint_policy.items() if key != "provider_version"}
    )
    tls_input = TlsPolicyInput.model_validate(row.tls_policy)
    endpoint_origin, base_path = _validated_location(
        row.endpoint_origin,
        row.base_path,
        tls_input,
        endpoint_input,
    )
    plaintext = ProviderCredentialVault.from_environment().decrypt_for_adapter(
        EncryptedProviderCredential(
            key_version=credential.key_version,
            nonce_b64=credential.nonce_b64,
            ciphertext_b64=credential.ciphertext_b64,
            credential_kind=credential.credential_kind,
        ),
        f"panel:{row.id}".encode(),
    )
    try:
        decoded = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
            "provider credential record is invalid",
        ) from exc
    if not isinstance(decoded, dict):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
            "provider credential record is invalid",
        )
    secret = cast(dict[str, object], decoded)
    if secret.get("auth_mode") != credential.credential_kind:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
            "provider credential record is invalid",
        )
    auth_mode = secret.get("auth_mode")
    bearer_value = secret.get("bearer_token")
    username_value = secret.get("username")
    password_value = secret.get("password")
    if auth_mode == "bearer_token" and isinstance(bearer_value, str):
        transport = await HttpxSanaei3xUiV370Transport.connect(
            endpoint_origin,
            base_path=base_path,
            bearer_token=bearer_value,
            verify_tls=tls_input.verify_tls,
            max_response_bytes=endpoint_input.max_response_bytes,
        )
        client = Sanaei3xUiV370Client(
            transport,
            base_path=base_path,
            bearer_token=bearer_value,
        )
    elif (
        auth_mode == "username_password"
        and isinstance(username_value, str)
        and isinstance(password_value, str)
    ):
        transport = await HttpxSanaei3xUiV370Transport.connect(
            endpoint_origin,
            base_path=base_path,
            username=username_value,
            password=password_value,
            verify_tls=tls_input.verify_tls,
            max_response_bytes=endpoint_input.max_response_bytes,
        )
        client = Sanaei3xUiV370Client(
            transport,
            base_path=base_path,
            session_csrf_token=transport.session_csrf_token,
        )
    else:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
            "provider credential record is invalid",
        )
    return transport, client


def _view(db: Session, row: PanelInstanceModel) -> PanelResponse:
    credential = _credential(db, row.id)
    connection = _last_test(db, row.id)
    return PanelResponse(
        id=row.id,
        public_reference=row.public_reference,
        display_name=row.display_name,
        provider_kind=row.provider_kind,
        provider_version=_provider_version(row),
        endpoint_origin=row.endpoint_origin,
        base_path=row.base_path,
        status=row.status,
        tls_policy=dict(row.tls_policy),
        endpoint_policy={
            key: value for key, value in row.endpoint_policy.items() if key != "provider_version"
        },
        optimistic_version=row.optimistic_version,
        credential=CredentialSummary(
            configured=credential is not None,
            credential_kind=credential.credential_kind if credential else None,
            key_version=credential.key_version if credential else None,
            updated_at=credential.created_at if credential else None,
        ),
        last_connection_test=(
            ConnectionSummary(
                status=connection.status,
                detected_version=connection.detected_version,
                contract_digest=connection.contract_digest,
                latency_ms=connection.latency_ms,
                safe_error_code=connection.safe_error_code,
                tested_at=connection.tested_at,
            )
            if connection
            else None
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/panels", response_model=PanelListResponse)
def list_panels(
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[AdminModel, Depends(require_perm("providers.read"))],
) -> PanelListResponse:
    rows = db.scalars(
        select(PanelInstanceModel).order_by(PanelInstanceModel.created_at.desc())
    ).all()
    return PanelListResponse(items=[_view(db, row) for row in rows])


@router.post("/panels", response_model=PanelResponse, status_code=status.HTTP_201_CREATED)
def create_panel(
    body: PanelCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("providers.manage"))],
) -> PanelResponse:
    contract = VERSIONED_CERTIFIED_CONTRACTS.get((body.provider_kind, body.provider_version))
    if contract is None:
        raise _safe_error("PROVIDER_VERSION_UNSUPPORTED", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.provider_kind is not ProviderKind.SANAEI_3X_UI:
        raise _safe_error("PROVIDER_VERSION_UNSUPPORTED", status.HTTP_422_UNPROCESSABLE_ENTITY)
    origin, base_path = _validated_location(
        body.endpoint_origin, body.base_path, body.tls_policy, body.endpoint_policy
    )
    now = datetime.now(UTC)
    endpoint_policy = body.endpoint_policy.model_dump()
    endpoint_policy["provider_version"] = body.provider_version
    row = PanelInstanceModel(
        id=str(uuid4()),
        public_reference=f"pnl_{uuid4().hex[:20]}",
        provider_kind=body.provider_kind.value,
        display_name=body.display_name.strip(),
        endpoint_origin=origin,
        base_path=base_path,
        status="DRAFT",
        tls_policy=body.tls_policy.model_dump(),
        endpoint_policy=endpoint_policy,
        optimistic_version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    _audit(
        db,
        admin,
        request,
        "provider.panel.created",
        row.id,
        {"provider_kind": row.provider_kind, "provider_version": contract.release_tag},
    )
    return _view(db, row)


@router.get("/panels/{public_reference}", response_model=PanelResponse)
def get_panel(
    public_reference: str,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[AdminModel, Depends(require_perm("providers.read"))],
) -> PanelResponse:
    return _view(db, _panel(db, public_reference))


@router.patch("/panels/{public_reference}", response_model=PanelResponse)
def update_panel(
    public_reference: str,
    body: PanelUpdateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("providers.manage"))],
) -> PanelResponse:
    row = _panel(db, public_reference)
    if row.optimistic_version != body.optimistic_version:
        raise _safe_error("CONCURRENT_MODIFICATION", status.HTTP_409_CONFLICT)
    tls_input = body.tls_policy or TlsPolicyInput.model_validate(row.tls_policy)
    current_endpoint_policy = {
        key: value for key, value in row.endpoint_policy.items() if key != "provider_version"
    }
    endpoint_input = body.endpoint_policy or EndpointPolicyInput.model_validate(
        current_endpoint_policy
    )
    endpoint_origin = body.endpoint_origin or row.endpoint_origin
    base_path = body.base_path if body.base_path is not None else row.base_path
    origin, normalized_base_path = _validated_location(
        endpoint_origin, base_path, tls_input, endpoint_input
    )
    connection_changed = (
        origin != row.endpoint_origin
        or normalized_base_path != row.base_path
        or tls_input.model_dump() != row.tls_policy
        or endpoint_input.model_dump() != current_endpoint_policy
    )
    endpoint_policy = endpoint_input.model_dump()
    endpoint_policy["provider_version"] = _provider_version(row)
    values: dict[str, object] = {
        "display_name": body.display_name.strip() if body.display_name else row.display_name,
        "status": body.status or row.status,
        "endpoint_origin": origin,
        "base_path": normalized_base_path,
        "tls_policy": tls_input.model_dump(),
        "endpoint_policy": endpoint_policy,
        "optimistic_version": body.optimistic_version + 1,
        "updated_at": datetime.now(UTC),
    }
    if connection_changed and values["status"] == "ACTIVE":
        values["status"] = "RECERTIFICATION_REQUIRED"
    result = db.execute(
        update(PanelInstanceModel)
        .where(
            PanelInstanceModel.id == row.id,
            PanelInstanceModel.optimistic_version == body.optimistic_version,
        )
        .values(**values)
    )
    if result.rowcount != 1:
        raise _safe_error("CONCURRENT_MODIFICATION", status.HTTP_409_CONFLICT)
    db.flush()
    db.expire(row)
    _audit(
        db,
        admin,
        request,
        "provider.panel.updated",
        row.id,
        {"connection_changed": connection_changed, "status": values["status"]},
    )
    return _view(db, row)


@router.put("/panels/{public_reference}/credential", response_model=CredentialSummary)
def replace_credential(
    public_reference: str,
    body: CredentialWriteRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("providers.manage_credentials"))],
) -> CredentialSummary:
    row = _panel(db, public_reference)
    if body.auth_mode == "bearer_token":
        if body.bearer_token is None or body.username is not None or body.password is not None:
            raise _safe_error("PROVIDER_CREDENTIAL_PAYLOAD_INVALID")
        secret = {
            "auth_mode": body.auth_mode,
            "bearer_token": body.bearer_token.get_secret_value(),
        }
    else:
        if body.username is None or body.password is None or body.bearer_token is not None:
            raise _safe_error("PROVIDER_CREDENTIAL_PAYLOAD_INVALID")
        secret = {
            "auth_mode": body.auth_mode,
            "username": body.username,
            "password": body.password.get_secret_value(),
        }
    try:
        encrypted = ProviderCredentialVault.from_environment().encrypt(
            json.dumps(secret, separators=(",", ":")),
            body.auth_mode,
            f"panel:{row.id}".encode(),
        )
    except ProviderError as exc:
        raise _safe_error(
            "PROVIDER_CREDENTIAL_VAULT_UNAVAILABLE", status.HTTP_503_SERVICE_UNAVAILABLE
        ) from exc
    now = datetime.now(UTC)
    db.execute(delete(PanelCredentialModel).where(PanelCredentialModel.panel_instance_id == row.id))
    db.add(
        PanelCredentialModel(
            id=str(uuid4()),
            panel_instance_id=row.id,
            credential_kind=encrypted.credential_kind,
            key_version=encrypted.key_version,
            nonce_b64=encrypted.nonce_b64,
            ciphertext_b64=encrypted.ciphertext_b64,
            created_at=now,
        )
    )
    row.status = "RECERTIFICATION_REQUIRED"
    row.optimistic_version += 1
    row.updated_at = now
    _audit(
        db,
        admin,
        request,
        "provider.credential.replaced",
        row.id,
        {"authentication_mode": body.auth_mode},
    )
    db.flush()
    return CredentialSummary(
        configured=True,
        credential_kind=body.auth_mode,
        key_version=encrypted.key_version,
        updated_at=now,
    )


@router.get("/panels/{public_reference}/capabilities", response_model=CapabilityResponse)
def panel_capabilities(
    public_reference: str,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[AdminModel, Depends(require_perm("providers.read"))],
) -> CapabilityResponse:
    row = _panel(db, public_reference)
    version = _provider_version(row)
    if row.provider_kind != ProviderKind.SANAEI_3X_UI.value or version != "v3.7.0":
        raise _safe_error("PROVIDER_VERSION_UNSUPPORTED", status.HTTP_422_UNPROCESSABLE_ENTITY)
    contract = SANAEI_3X_UI_V370_CAPABILITIES.contract
    return CapabilityResponse(
        provider_kind=row.provider_kind,
        provider_version=version,
        contract_digest=contract.contract_digest,
        release_commit=contract.commit_sha,
        authentication_preference=[
            value.value for value in SANAEI_3X_UI_V370_CAPABILITIES.authentication_preference
        ],
        required_bearer_scope=SANAEI_3X_UI_V370_CAPABILITIES.required_bearer_scope,
        operations=sorted(value.value for value in SANAEI_3X_UI_V370_CAPABILITIES.operations),
        writes_enabled_by_default=SANAEI_3X_UI_V370_CAPABILITIES.writes_enabled_by_default,
    )


@router.get("/panels/{public_reference}/connection-tests", response_model=list[ConnectionSummary])
def connection_tests(
    public_reference: str,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[AdminModel, Depends(require_perm("providers.read_diagnostics"))],
) -> list[ConnectionSummary]:
    row = _panel(db, public_reference)
    tests = db.scalars(
        select(ProviderConnectionTestModel)
        .where(ProviderConnectionTestModel.panel_instance_id == row.id)
        .order_by(ProviderConnectionTestModel.tested_at.desc())
        .limit(50)
    ).all()
    return [
        ConnectionSummary(
            status=item.status,
            detected_version=item.detected_version,
            contract_digest=item.contract_digest,
            latency_ms=item.latency_ms,
            safe_error_code=item.safe_error_code,
            tested_at=item.tested_at,
        )
        for item in tests
    ]


@router.post("/panels/{public_reference}/test-connection", response_model=ConnectionSummary)
async def test_panel_connection(
    public_reference: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("providers.test_connection"))],
) -> ConnectionSummary:
    row = _panel(db, public_reference)
    now = datetime.now(UTC)
    detected_version: str | None = None
    digest: str | None = None
    latency_ms: int | None = None
    safe_error_code: str | None = None
    connection_status = "FAILED"
    transport: HttpxSanaei3xUiV370Transport | None = None
    try:
        transport, client = await _live_client(db, row)
        started = datetime.now(UTC)
        server = await client.server_status()
        latency_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
        version_value = server.get("panelVersion")
        if not isinstance(version_value, str) or not version_value.strip():
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                "provider version is missing",
            )
        detected_version = version_value.strip()
        expected = _provider_version(row)
        if detected_version not in {expected, expected.lstrip("v")}:
            safe_error_code = "PROVIDER_VERSION_UNSUPPORTED"
            connection_status = "VERSION_UNSUPPORTED"
        else:
            digest = SANAEI_3X_UI_V370_CAPABILITIES.contract.contract_digest
            connection_status = "CONTRACT_VERIFIED"
    except Exception as exc:  # provider failures are stored only as safe codes
        safe_error_code = _connection_failure_code(exc)
    finally:
        if transport is not None:
            await transport.aclose()
    test = ProviderConnectionTestModel(
        id=str(uuid4()),
        panel_instance_id=row.id,
        status=connection_status,
        detected_version=detected_version,
        contract_digest=digest,
        latency_ms=latency_ms,
        safe_error_code=safe_error_code,
        tested_at=now,
    )
    db.add(test)
    if connection_status == "CONTRACT_VERIFIED":
        row.status = "ACTIVE"
    elif row.status == "ACTIVE":
        row.status = "RECERTIFICATION_REQUIRED"
    row.optimistic_version += 1
    row.updated_at = now
    _audit(
        db,
        admin,
        request,
        "provider.connection_test.completed",
        row.id,
        {"result": connection_status, "safe_error_code": safe_error_code or "NONE"},
    )
    return ConnectionSummary(
        status=connection_status,
        detected_version=detected_version,
        contract_digest=digest,
        latency_ms=latency_ms,
        safe_error_code=safe_error_code,
        tested_at=now,
    )


@router.post("/panels/{public_reference}/sync", response_model=SyncResponse)
async def sync_panel_inventory(
    public_reference: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("providers.sync"))],
) -> SyncResponse:
    row = _panel(db, public_reference)
    now = datetime.now(UTC)
    sync_reference = f"sync_{uuid4().hex[:20]}"
    run = ProviderSyncRunModel(
        id=str(uuid4()),
        sync_reference=sync_reference,
        panel_instance_id=row.id,
        adapter_code="sanaei_3x_ui",
        adapter_version="0.7.0",
        status="RUNNING",
        started_at=now,
        completed_at=None,
    )
    db.add(run)
    db.flush()
    detected_version: str | None = None
    safe_error_code: str | None = None
    inbound_count = 0
    transport: HttpxSanaei3xUiV370Transport | None = None
    try:
        transport, client = await _live_client(db, row)
        server = await client.server_status()
        version_value = server.get("panelVersion")
        detected_version = version_value.strip() if isinstance(version_value, str) else None
        expected = _provider_version(row)
        if detected_version not in {expected, expected.lstrip("v")}:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_VERSION_UNSUPPORTED,
                "provider version does not match the certified contract",
            )
        options = await client.list_inbound_options()
        observed_at = datetime.now(UTC)
        for option in options:
            db.add(
                ProviderInboundSnapshotModel(
                    id=str(uuid4()),
                    panel_instance_id=row.id,
                    sync_run_id=run.id,
                    remote_identifier=str(option.inbound_id),
                    status="ACTIVE" if option.enabled else "DISABLED",
                    sanitized_payload={
                        "remark": option.remark,
                        "tag": option.tag,
                        "protocol": option.protocol,
                        "port": option.port,
                        "enabled": option.enabled,
                        "node_id": option.node_id,
                        "tls_flow_capable": option.tls_flow_capable,
                    },
                    observed_at=observed_at,
                )
            )
        inbound_count = len(options)
        run.status = "SUCCESS"
        row.status = "ACTIVE"
    except Exception as exc:  # retain safe failed-run evidence for operators
        run.status = "FAILED"
        safe_error_code = _connection_failure_code(exc)
        if row.status == "ACTIVE":
            row.status = "RECERTIFICATION_REQUIRED"
    finally:
        if transport is not None:
            await transport.aclose()
    completed_at = datetime.now(UTC)
    run.completed_at = completed_at
    row.updated_at = completed_at
    row.optimistic_version += 1
    _audit(
        db,
        admin,
        request,
        "provider.inventory_sync.completed",
        row.id,
        {
            "result": run.status,
            "inbound_count": inbound_count,
            "safe_error_code": safe_error_code or "NONE",
        },
    )
    return SyncResponse(
        sync_reference=sync_reference,
        status=run.status,
        inbound_count=inbound_count,
        detected_version=detected_version,
        safe_error_code=safe_error_code,
        completed_at=completed_at,
    )


@router.get("/panels/{public_reference}/inbounds", response_model=list[InboundSnapshotResponse])
def panel_inbounds(
    public_reference: str,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[AdminModel, Depends(require_perm("providers.read_inventory"))],
) -> list[InboundSnapshotResponse]:
    row = _panel(db, public_reference)
    snapshots = db.execute(
        select(ProviderInboundSnapshotModel, ProviderSyncRunModel.sync_reference)
        .outerjoin(
            ProviderSyncRunModel,
            ProviderSyncRunModel.id == ProviderInboundSnapshotModel.sync_run_id,
        )
        .where(ProviderInboundSnapshotModel.panel_instance_id == row.id)
        .order_by(ProviderInboundSnapshotModel.observed_at.desc())
        .limit(500)
    ).all()
    return [
        InboundSnapshotResponse(
            remote_identifier=snapshot.remote_identifier or "unknown",
            status=snapshot.status,
            sanitized_payload=dict(snapshot.sanitized_payload),
            observed_at=snapshot.observed_at,
            sync_reference=sync_reference,
        )
        for snapshot, sync_reference in snapshots
    ]
