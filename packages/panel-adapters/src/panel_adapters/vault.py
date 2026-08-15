"""Versioned provider credential vault using reviewed AEAD encryption.

New records use AES-256-GCM and encode the algorithm in ``key_version``. Legacy
XOR/HMAC records remain decryptable only for rotation; encryption never creates
legacy records. Authenticated AAD binds ciphertext to its panel record.
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

AEAD_PREFIX = "aead:"


@dataclass(frozen=True)
class EncryptedProviderCredential:
    key_version: str
    nonce_b64: str
    ciphertext_b64: str
    credential_kind: str


class ProviderCredentialVault:
    def __init__(self, master_key_b64: str, key_version: str = "v1") -> None:
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
        self._key_version = key_version.removeprefix(AEAD_PREFIX)

    @classmethod
    def from_environment(cls) -> ProviderCredentialVault:
        value = os.environ.get("PROVIDER_VAULT_MASTER_KEY_B64")
        if not value:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "vault key unavailable"
            )
        return cls(value, os.environ.get("PROVIDER_VAULT_KEY_VERSION", "v1"))

    def encrypt(
        self, plaintext: str, credential_kind: str, aad: bytes
    ) -> EncryptedProviderCredential:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext.encode(), aad)
        return EncryptedProviderCredential(
            AEAD_PREFIX + self._key_version,
            base64.urlsafe_b64encode(nonce).decode(),
            base64.urlsafe_b64encode(ciphertext).decode(),
            credential_kind,
        )

    def decrypt_for_adapter(self, record: EncryptedProviderCredential, aad: bytes) -> str:
        if record.key_version.startswith(AEAD_PREFIX):
            if record.key_version != AEAD_PREFIX + self._key_version:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                    "vault key version unavailable",
                )
            try:
                nonce = base64.urlsafe_b64decode(record.nonce_b64)
                ciphertext = base64.urlsafe_b64decode(record.ciphertext_b64)
                return AESGCM(self._key).decrypt(nonce, ciphertext, aad).decode()
            except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                    "credential authentication failed",
                ) from exc
        return self._decrypt_legacy_for_rotation(record, aad)

    def _decrypt_legacy_for_rotation(self, record: EncryptedProviderCredential, aad: bytes) -> str:
        """Read an authenticated legacy record so operators can rotate it to AEAD."""
        try:
            nonce = base64.urlsafe_b64decode(record.nonce_b64)
            payload = base64.urlsafe_b64decode(record.ciphertext_b64)
            tag, ciphertext = payload[:32], payload[32:]
            expected = hmac.new(self._key, nonce + aad + ciphertext, hashlib.sha256).digest()
            if not hmac.compare_digest(tag, expected):
                raise ValueError("legacy authentication failed")
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
            return bytes(a ^ b for a, b in zip(ciphertext, stream, strict=True)).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "legacy credential authentication failed",
            ) from exc
