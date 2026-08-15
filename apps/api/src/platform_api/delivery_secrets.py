from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import cast

from cryptography.fernet import Fernet, InvalidToken

_ALLOWED_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://")
_MAX_LINKS = 16
_MAX_LINK_BYTES = 4096
_MAX_PAYLOAD_BYTES = 32768


class DeliveryPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class EncryptedDeliveryPayload:
    key_version: str
    ciphertext: str
    sha256: str


class DeliveryPayloadCipher:
    def __init__(self, active_key: str, key_version: str, keyring: dict[str, str] | None = None):
        if not key_version.strip():
            raise DeliveryPayloadError("delivery encryption key version required")
        keys = dict(keyring or {})
        existing = keys.get(key_version)
        if existing is not None and existing != active_key:
            raise DeliveryPayloadError("delivery active key conflicts with keyring")
        keys[key_version] = active_key
        try:
            self._fernets = {version: Fernet(value.encode()) for version, value in keys.items()}
        except (ValueError, TypeError) as exc:
            raise DeliveryPayloadError("invalid delivery encryption key") from exc
        self._active_version = key_version

    @classmethod
    def from_environment(cls) -> DeliveryPayloadCipher:
        active_key = os.environ.get("VPN_SALE_DELIVERY_ENCRYPTION_KEY", "")
        key_version = os.environ.get("VPN_SALE_DELIVERY_ENCRYPTION_KEY_VERSION", "delivery-v1")
        if not active_key:
            raise DeliveryPayloadError("delivery encryption key unavailable")
        keyring_raw = os.environ.get("VPN_SALE_DELIVERY_DECRYPT_KEYS_JSON", "")
        keyring: dict[str, str] = {}
        if keyring_raw:
            try:
                parsed: object = json.loads(keyring_raw)
            except json.JSONDecodeError as exc:
                raise DeliveryPayloadError("delivery keyring invalid") from exc
            if not isinstance(parsed, dict):
                raise DeliveryPayloadError("delivery keyring invalid")
            for version, key in cast(dict[object, object], parsed).items():
                if not isinstance(version, str) or not isinstance(key, str):
                    raise DeliveryPayloadError("delivery keyring invalid")
                keyring[version] = key
        return cls(active_key, key_version, keyring)

    @staticmethod
    def validate_links(links: object) -> tuple[str, ...]:
        if not isinstance(links, list) or not 1 <= len(links) <= _MAX_LINKS:
            raise DeliveryPayloadError("provider delivery links invalid")
        result: list[str] = []
        total = 0
        for raw in links:
            if not isinstance(raw, str):
                raise DeliveryPayloadError("provider delivery link invalid")
            link = raw.strip()
            encoded = link.encode("utf-8")
            if (
                not link.startswith(_ALLOWED_SCHEMES)
                or not encoded
                or len(encoded) > _MAX_LINK_BYTES
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in link)
            ):
                raise DeliveryPayloadError("provider delivery link invalid")
            total += len(encoded)
            if total > _MAX_PAYLOAD_BYTES:
                raise DeliveryPayloadError("provider delivery payload too large")
            result.append(link)
        return tuple(result)

    @staticmethod
    def _canonical(service_id: str, links: tuple[str, ...]) -> bytes:
        return json.dumps(
            {"service_id": service_id, "links": list(links)},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()

    def encrypt(self, service_id: str, links: tuple[str, ...]) -> EncryptedDeliveryPayload:
        canonical = self._canonical(service_id, links)
        if len(canonical) > _MAX_PAYLOAD_BYTES + 1024:
            raise DeliveryPayloadError("delivery payload too large")
        cipher = self._fernets[self._active_version].encrypt(canonical).decode()
        digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
        return EncryptedDeliveryPayload(self._active_version, cipher, digest)

    def decrypt(
        self,
        service_id: str,
        key_version: str | None,
        ciphertext: str | None,
        expected_sha256: str | None,
    ) -> tuple[str, ...]:
        if not key_version or not ciphertext or not expected_sha256:
            raise DeliveryPayloadError("delivery payload unavailable")
        fernet = self._fernets.get(key_version)
        if fernet is None:
            raise DeliveryPayloadError("delivery encryption key version unavailable")
        try:
            canonical = fernet.decrypt(ciphertext.encode())
        except InvalidToken as exc:
            raise DeliveryPayloadError("delivery payload authentication failed") from exc
        digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
        if digest != expected_sha256:
            raise DeliveryPayloadError("delivery payload digest mismatch")
        try:
            data: object = json.loads(canonical)
        except json.JSONDecodeError as exc:
            raise DeliveryPayloadError("delivery payload invalid") from exc
        if not isinstance(data, dict):
            raise DeliveryPayloadError("delivery payload invalid")
        mapping = cast(dict[str, object], data)
        if mapping.get("service_id") != service_id:
            raise DeliveryPayloadError("delivery payload service mismatch")
        return self.validate_links(mapping.get("links"))
