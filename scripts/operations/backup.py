from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"VPN-SALE-BACKUP\x00\x01"
NONCE_SIZE = 12
KEY_ENV = "VPN_SALE_BACKUP_MASTER_KEY_B64"


def _decode_key(value: bytes) -> bytes:
    candidate = value.strip()
    if len(candidate) == 32:
        return candidate
    try:
        decoded = base64.b64decode(candidate, altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SystemExit("backup encryption key is not valid base64") from exc
    if len(decoded) != 32:
        raise SystemExit("backup encryption key must decode to exactly 32 bytes")
    return decoded


def load_key(key_file: str | None) -> bytes:
    if key_file:
        return _decode_key(Path(key_file).read_bytes())
    encoded = os.environ.get(KEY_ENV, "")
    if not encoded:
        raise SystemExit(f"{KEY_ENV} or --key-file is required")
    return _decode_key(encoded.encode())


def _write_atomic(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def encrypt_backup(payload: bytes, environment: str, key: bytes) -> bytes:
    encoded_environment = environment.encode("ascii")
    if len(encoded_environment) > 255:
        raise ValueError("environment identifier is too long")
    header = MAGIC + bytes([len(encoded_environment)]) + encoded_environment
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, payload, header)
    return header + nonce + ciphertext


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment", required=True, choices=["LOCAL", "TEST", "CI", "STAGING", "PRODUCTION"]
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--key-file")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    destination = Path(args.destination).resolve()
    if source == destination:
        raise SystemExit("backup source and destination must differ")
    payload = source.read_bytes()
    encrypted = encrypt_backup(payload, args.environment, load_key(args.key_file))
    _write_atomic(destination, encrypted)
    manifest = {
        "environment": args.environment,
        "completed_at": datetime.now(UTC).isoformat(),
        "checksum_sha256": hashlib.sha256(encrypted).hexdigest(),
        "encrypted_object_reference": destination.name,
        "encryption": "AES-256-GCM",
        "format_version": 1,
        "retention_class": "standard",
        "size_bytes": len(encrypted),
    }
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
