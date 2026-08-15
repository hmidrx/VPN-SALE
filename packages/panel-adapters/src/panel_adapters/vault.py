"""Provider credential vault using authenticated AEAD encryption.

New records use AES-256-GCM with authenticated record context. Legacy records from the
pre-AEAD implementation are read only when an explicit migration-only switch is enabled;
production provider writes must use an ``aead-*`` key version.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from vpnsale_domain.providers import ProviderError, ProviderErrorCode


@dataclass(frozen=True)
class EncryptedProviderCredential:
    key_version: str
    nonce_b64: str
    ciphertext_b64: str
    credential_kind: str


class ProviderCredentialVault:
    def __init__(
        self,
        master_key_b64: str,
        key_version: str = "aead-v1",
        *,
        allow_legacy_decrypt: bool = False,
    ) -> None:
        try:
            key = base64.urlsafe_b64decode(master_key_b64)
        except (ValueError, TypeError) as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "invalid vault key"
            ) from exc
        if len(key) != 32:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "invalid vault key"
            )
        self._key = key
        self._key_version = key_version
        self._allow_legacy_decrypt = allow_legacy_decrypt

    @classmethod
    def from_environment(cls) -> ProviderCredentialVault:
        value = os.environ.get("PROVIDER_VAULT_MASTER_KEY_B64")
        if not value:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "vault key unavailable"
            )
        return cls(
            value,
            os.environ.get("PROVIDER_VAULT_KEY_VERSION", "aead-v1"),
            allow_legacy_decrypt=(
                os.environ.get("PROVIDER_VAULT_ALLOW_LEGACY_READ", "false").lower() == "true"
            ),
        )

    @staticmethod
    def _record_aad(credential_kind: str, aad: bytes) -> bytes:
        return b"vpnsale-provider-credential-aead-v1\x00" + credential_kind.encode() + b"\x00" + aad

    def encrypt(
        self, plaintext: str, credential_kind: str, aad: bytes
    ) -> EncryptedProviderCredential:
        if not self._key_version.startswith("aead-"):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "new credentials require an AEAD key version",
            )
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce,
            plaintext.encode(),
            self._record_aad(credential_kind, aad),
        )
        return EncryptedProviderCredential(
            self._key_version,
            base64.urlsafe_b64encode(nonce).decode(),
            base64.urlsafe_b64encode(ciphertext).decode(),
            credential_kind,
        )

    def decrypt_for_adapter(self, record: EncryptedProviderCredential, aad: bytes) -> str:
        if record.key_version.startswith("aead-"):
            return self._decrypt_aead(record, aad)
        if not self._allow_legacy_decrypt:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "legacy provider credential requires controlled migration",
            )
        return self._decrypt_legacy(record, aad)

    def _decrypt_aead(self, record: EncryptedProviderCredential, aad: bytes) -> str:
        try:
            nonce = base64.urlsafe_b64decode(record.nonce_b64)
            ciphertext = base64.urlsafe_b64decode(record.ciphertext_b64)
            if len(nonce) != 12:
                raise ValueError("invalid nonce")
            plaintext = AESGCM(self._key).decrypt(
                nonce,
                ciphertext,
                self._record_aad(record.credential_kind, aad),
            )
            return plaintext.decode()
        except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "provider credential authentication failed",
            ) from exc

    def _decrypt_legacy(self, record: EncryptedProviderCredential, aad: bytes) -> str:
        """Migration-only reader for the historical XOR+HMAC record format."""
        try:
            nonce = base64.urlsafe_b64decode(record.nonce_b64)
            payload = base64.urlsafe_b64decode(record.ciphertext_b64)
        except (ValueError, TypeError) as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "legacy credential invalid"
            ) from exc
        if len(payload) < 32:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "legacy credential invalid"
            )
        tag, ciphertext = payload[:32], payload[32:]
        expected = hmac.new(self._key, nonce + aad + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "legacy credential authentication failed",
            )
        blocks: list[bytes] = []
        counter = 0
        while sum(len(block) for block in blocks) < len(ciphertext):
            counter += 1
            blocks.append(
                hmac.new(
                    self._key,
                    nonce + aad + counter.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
        stream = b"".join(blocks)[: len(ciphertext)]
        try:
            return bytes(a ^ b for a, b in zip(ciphertext, stream, strict=True)).decode()
        except UnicodeDecodeError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "legacy credential invalid"
            ) from exc
