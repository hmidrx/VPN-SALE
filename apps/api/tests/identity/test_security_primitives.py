from __future__ import annotations

import pytest

from platform_api.identity.security import (
    Argon2idPasswordHasher,
    EncryptedSecret,
    FernetSecretEncryptor,
    OpaqueTokenService,
    SecretEncryptionError,
    deterministic_development_fernet_key,
)


def test_argon2id_hash_verify_and_rehash() -> None:
    hasher = Argon2idPasswordHasher(time_cost=2, memory_cost=8192, parallelism=1)
    password_hash = hasher.hash("correct horse battery staple")
    assert password_hash.startswith("$argon2id$")
    assert hasher.verify("correct horse battery staple", password_hash)
    assert not hasher.verify("wrong", password_hash)
    stronger = Argon2idPasswordHasher(time_cost=3, memory_cost=8192, parallelism=1)
    assert stronger.needs_rehash(password_hash)


def test_opaque_tokens_are_random_and_hashed() -> None:
    service = OpaqueTokenService()
    first = service.generate()
    second = service.generate()
    assert first != second
    assert len(first) >= 43
    digest = service.hash(first)
    assert first not in digest
    assert service.verify(first, digest)
    assert not service.verify(second, digest)


def test_encrypted_secret_round_trip_and_wrong_key_failure() -> None:
    encryptor = FernetSecretEncryptor(
        key=deterministic_development_fernet_key(), key_version="dev-v1"
    )
    record = encryptor.encrypt("totp-secret-placeholder")
    assert record.key_version == "dev-v1"
    assert "totp-secret-placeholder" not in record.ciphertext
    assert encryptor.decrypt(record) == "totp-secret-placeholder"
    wrong = FernetSecretEncryptor(
        key="MTEwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=", key_version="dev-v2"
    )
    with pytest.raises(SecretEncryptionError):
        wrong.decrypt(EncryptedSecret(key_version=record.key_version, ciphertext=record.ciphertext))
