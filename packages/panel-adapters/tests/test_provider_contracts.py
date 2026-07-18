from __future__ import annotations

import asyncio
import base64

import pytest
from panel_adapters.contracts import AdapterRegistry, EndpointValidator
from panel_adapters.live_certification import main
from panel_adapters.vault import ProviderCredentialVault
from vpnsale_domain.providers import (
    CapabilitySupport,
    PanelEndpointPolicy,
    PanelTlsPolicy,
    ProviderCapability,
    ProviderError,
    ProviderErrorCode,
    ProviderKind,
)


class MockTransport:
    def __init__(self, version: str) -> None:
        self.version = version
        self.paths: list[str] = []

    async def get(self, path: str, headers: dict[str, str] | None = None):
        from panel_adapters.contracts import SanitizedHttpResponse

        self.paths.append(path)
        if "status" in path:
            return SanitizedHttpResponse(200, {"version": self.version}, {}, 0)
        return SanitizedHttpResponse(
            200,
            [
                {
                    "id": 1,
                    "remark": "safe",
                    "protocol": "vless",
                    "port": 443,
                    "clients": [{"id": "remote-client", "up": 1, "down": 2, "total": 0}],
                }
            ],
            {},
            0,
        )

    async def post_form(
        self, path: str, form: dict[str, str], headers: dict[str, str] | None = None
    ):
        raise AssertionError("mutation/session calls are not expected in deterministic read test")


@pytest.mark.parametrize(
    ("kind", "version"),
    [
        (ProviderKind.SANAEI_3X_UI, "3.5.0"),
        (ProviderKind.ALIREZA_X_UI, "1.11.3"),
        (ProviderKind.PASARGUARD, "5.1.0"),
    ],
)
def test_certified_adapters_detect_exact_version(kind: ProviderKind, version: str) -> None:
    adapter = AdapterRegistry.default().adapters[kind]
    detected = asyncio.run(adapter.detect_version(MockTransport(version)))
    assert detected.remote_version == version
    assert detected.certification_status == "CONTRACT_VERIFIED"


def test_unknown_version_fails_closed() -> None:
    adapter = AdapterRegistry.default().adapters[ProviderKind.SANAEI_3X_UI]
    detected = asyncio.run(adapter.detect_version(MockTransport("9.9.9")))
    assert detected.certification_status == "VERSION_UNSUPPORTED"


def test_write_capabilities_are_disabled() -> None:
    adapter = AdapterRegistry.default().adapters[ProviderKind.PASARGUARD]
    disabled = [x for x in adapter.capabilities if x.capability == ProviderCapability.CLIENT_CREATE]
    assert disabled[0].support is CapabilitySupport.DISABLED_BY_POLICY
    with pytest.raises(ProviderError) as exc:
        asyncio.run(adapter.mutation_disabled(ProviderCapability.CLIENT_CREATE))
    assert exc.value.code is ProviderErrorCode.PROVIDER_OPERATION_NOT_ENABLED


def test_vault_encrypts_without_plaintext_recovery_api() -> None:
    key = base64.urlsafe_b64encode(b"0" * 32).decode()
    vault = ProviderCredentialVault(key)
    encrypted = vault.encrypt("secret-token", "api_token", b"panel")
    assert "secret-token" not in encrypted.ciphertext_b64
    assert vault.decrypt_for_adapter(encrypted, b"panel") == "secret-token"


def test_endpoint_validator_rejects_unsafe_schemes() -> None:
    with pytest.raises(ProviderError) as exc:
        EndpointValidator().validate("file:///etc/passwd", PanelEndpointPolicy(), PanelTlsPolicy())
    assert exc.value.code is ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED


def test_live_certification_requires_acknowledgement(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--panel-reference", "panel_123"]) == 2
    assert "without --live" in capsys.readouterr().out
