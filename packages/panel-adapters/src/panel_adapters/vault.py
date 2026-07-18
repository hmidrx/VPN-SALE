"""One-way provider credential vault with authenticated ciphertext records.

The project environment does not yet pin an AEAD package; this module keeps the
vault boundary narrow and stores only nonce, key version and authenticated
ciphertext. Production deployments should back the same interface with KMS or a
reviewed AEAD package before live credentials are accepted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

from vpnsale_domain.providers import ProviderError, ProviderErrorCode


@dataclass(frozen=True)
class EncryptedProviderCredential:
    key_version: str
    nonce_b64: str
    ciphertext_b64: str
    credential_kind: str


class ProviderCredentialVault:
    def __init__(self, master_key_b64: str, key_version: str = "v1") -> None:
        key = base64.urlsafe_b64decode(master_key_b64)
        if len(key) != 32:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "invalid vault key"
            )
        self._key = key
        self._key_version = key_version

    @classmethod
    def from_environment(cls) -> ProviderCredentialVault:
        value = os.environ.get("PROVIDER_VAULT_MASTER_KEY_B64")
        if not value:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "vault key unavailable"
            )
        return cls(value, os.environ.get("PROVIDER_VAULT_KEY_VERSION", "v1"))

    def _keystream(self, nonce: bytes, aad: bytes, size: int) -> bytes:
        blocks: list[bytes] = []
        counter = 0
        while sum(len(block) for block in blocks) < size:
            counter += 1
            blocks.append(
                hmac.new(
                    self._key,
                    nonce + aad + counter.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
        return b"".join(blocks)[:size]

    def encrypt(
        self, plaintext: str, credential_kind: str, aad: bytes
    ) -> EncryptedProviderCredential:
        nonce = os.urandom(16)
        payload = plaintext.encode()
        stream = self._keystream(nonce, aad, len(payload))
        ciphertext = bytes(a ^ b for a, b in zip(payload, stream, strict=True))
        tag = hmac.new(self._key, nonce + aad + ciphertext, hashlib.sha256).digest()
        return EncryptedProviderCredential(
            self._key_version,
            base64.urlsafe_b64encode(nonce).decode(),
            base64.urlsafe_b64encode(tag + ciphertext).decode(),
            credential_kind,
        )

    def decrypt_for_adapter(self, record: EncryptedProviderCredential, aad: bytes) -> str:
        nonce = base64.urlsafe_b64decode(record.nonce_b64)
        payload = base64.urlsafe_b64decode(record.ciphertext_b64)
        tag, ciphertext = payload[:32], payload[32:]
        expected = hmac.new(self._key, nonce + aad + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "credential tag invalid"
            )
        stream = self._keystream(nonce, aad, len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, stream, strict=True)).decode()
