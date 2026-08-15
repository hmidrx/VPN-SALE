"""Provider credential vault using authenticated AEAD encryption.

New records use AES-256-GCM with authenticated record context. The active key version
encrypts new credentials while an explicit decrypt-only keyring can retain previous AEAD
versions during rotation. Legacy pre-AEAD records remain migration-only and live provider
writes require an ``aead-*`` record version.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

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
        decryption_keys_b64: Mapping[str, str] | None = None,
    ) -> None:
        active_key = self._decode_key(master_key_b64)
        if not key_version.startswith("aead-"):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "active provider vault key version must use AEAD",
            )
        keys: dict[str, bytes] = {}
        for version, encoded in (decryption_keys_b64 or {}).items():
            if not version:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                    "invalid provider vault key version",
                )
            keys[version] = self._decode_key(encoded)
        existing_active = keys.get(key_version)
        if existing_active is not None and not hmac.compare_digest(existing_active, active_key):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "provider vault active key conflicts with decrypt keyring",
            )
        keys[key_version] = active_key
        self._active_key = active_key
        self._key_version = key_version
        self._keys = keys
        self._allow_legacy_decrypt = allow_legacy_decrypt

    @staticmethod
    def _decode_key(value: str) -> bytes:
        try:
            key = base64.urlsafe_b64decode(value)
        except (binascii.Error, ValueError, TypeError) as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "invalid vault key"
            ) from exc
        if len(key) != 32:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "invalid vault key"
            )
        return key

    @classmethod
    def from_environment(cls) -> ProviderCredentialVault:
        value = os.environ.get("PROVIDER_VAULT_MASTER_KEY_B64")
        if not value:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "vault key unavailable"
            )
        keyring_raw = os.environ.get("PROVIDER_VAULT_DECRYPT_KEYS_JSON", "")
        keyring: dict[str, str] = {}
        if keyring_raw:
            try:
                parsed: object = json.loads(keyring_raw)
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                    "provider vault keyring configuration invalid",
                ) from exc
            if not isinstance(parsed, dict):
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                    "provider vault keyring configuration invalid",
                )
            for version, encoded in cast(dict[object, object], parsed).items():
                if not isinstance(version, str) or not isinstance(encoded, str):
                    raise ProviderError(
                        ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                        "provider vault keyring configuration invalid",
                    )
                keyring[version] = encoded
        return cls(
            value,
            os.environ.get("PROVIDER_VAULT_KEY_VERSION", "aead-v1"),
            allow_legacy_decrypt=(
                os.environ.get("PROVIDER_VAULT_ALLOW_LEGACY_READ", "false").lower() == "true"
            ),
            decryption_keys_b64=keyring,
        )

    @staticmethod
    def _record_aad(credential_kind: str, aad: bytes) -> bytes:
        return b"vpnsale-provider-credential-aead-v1\x00" + credential_kind.encode() + b"\x00" + aad

    def encrypt(
        self, plaintext: str, credential_kind: str, aad: bytes
    ) -> EncryptedProviderCredential:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._active_key).encrypt(
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
        key = self._keys.get(record.key_version)
        if key is None:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "provider credential key version unavailable",
            )
        try:
            nonce = base64.urlsafe_b64decode(record.nonce_b64)
            ciphertext = base64.urlsafe_b64decode(record.ciphertext_b64)
            if len(nonce) != 12:
                raise ValueError("invalid nonce")
            plaintext = AESGCM(key).decrypt(
                nonce,
                ciphertext,
                self._record_aad(record.credential_kind, aad),
            )
            return plaintext.decode()
        except (binascii.Error, InvalidTag, ValueError, UnicodeDecodeError) as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
                "provider credential authentication failed",
            ) from exc

    def _decrypt_legacy(self, record: EncryptedProviderCredential, aad: bytes) -> str:
        """Migration-only reader for the historical XOR+HMAC record format."""
        key = self._keys.get(record.key_version, self._active_key)
        try:
            nonce = base64.urlsafe_b64decode(record.nonce_b64)
            payload = base64.urlsafe_b64decode(record.ciphertext_b64)
        except (binascii.Error, ValueError, TypeError) as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "legacy credential invalid"
            ) from exc
        if len(payload) < 32:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "legacy credential invalid"
            )
        tag, ciphertext = payload[:32], payload[32:]
        expected = hmac.new(key, nonce + aad + ciphertext, hashlib.sha256).digest()
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
                    key,
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
