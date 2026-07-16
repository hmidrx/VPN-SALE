from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken


class PasswordHashingError(ValueError):
    pass


class PasswordHasherProtocol(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, password: str, password_hash: str) -> bool: ...
    def needs_rehash(self, password_hash: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class Argon2idPasswordHasher:
    time_cost: int = 3
    memory_cost: int = 65536
    parallelism: int = 4
    hash_len: int = 32
    salt_len: int = 16

    def _hasher(self) -> PasswordHasher:
        return PasswordHasher(
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_len,
            salt_len=self.salt_len,
        )

    def hash(self, password: str) -> str:
        if not password:
            raise PasswordHashingError("password is required")
        return self._hasher().hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher().verify(password_hash, password)
        except (VerifyMismatchError, Argon2Error, ValueError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher().check_needs_rehash(password_hash)
        except (Argon2Error, ValueError):
            return True


@dataclass(frozen=True, slots=True)
class OpaqueTokenService:
    bytes_length: int = 32
    hash_salt: str = "vpnsale-identity-token-v1"

    def generate(self) -> str:
        if self.bytes_length < 32:
            raise ValueError("opaque tokens must use at least 256 bits of entropy")
        return secrets.token_urlsafe(self.bytes_length)

    def hash(self, token: str) -> str:
        digest = hashlib.sha256(f"{self.hash_salt}:{token}".encode()).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def verify(self, token: str, token_hash: str) -> bool:
        return hmac.compare_digest(self.hash(token), token_hash)


@dataclass(frozen=True, slots=True)
class EncryptedSecret:
    key_version: str
    ciphertext: str


class SecretEncryptionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FernetSecretEncryptor:
    key: str
    key_version: str

    def __post_init__(self) -> None:
        try:
            Fernet(self.key.encode())
        except (ValueError, TypeError) as exc:
            raise SecretEncryptionError("invalid identity encryption key") from exc
        if not self.key_version.strip():
            raise SecretEncryptionError("identity encryption key version is required")

    def _fernet(self) -> Fernet:
        return Fernet(self.key.encode())

    def encrypt(self, plaintext: str) -> EncryptedSecret:
        if not plaintext:
            raise SecretEncryptionError("secret is required")
        return EncryptedSecret(
            key_version=self.key_version,
            ciphertext=self._fernet().encrypt(plaintext.encode()).decode(),
        )

    def decrypt(self, record: EncryptedSecret) -> str:
        try:
            return self._fernet().decrypt(record.ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretEncryptionError("secret could not be decrypted") from exc


def deterministic_development_fernet_key() -> str:
    return base64.urlsafe_b64encode(b"0" * 32).decode()
