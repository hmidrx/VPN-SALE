from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backup import MAGIC, NONCE_SIZE, _write_atomic, load_key
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def decrypt_backup(encrypted: bytes, key: bytes) -> tuple[str, bytes]:
    if not encrypted.startswith(MAGIC) or len(encrypted) <= len(MAGIC):
        raise SystemExit("unsupported or malformed backup envelope")
    environment_size = encrypted[len(MAGIC)]
    header_end = len(MAGIC) + 1 + environment_size
    minimum_size = header_end + NONCE_SIZE + 16
    if environment_size == 0 or len(encrypted) < minimum_size:
        raise SystemExit("unsupported or malformed backup envelope")
    header = encrypted[:header_end]
    try:
        source_environment = encrypted[len(MAGIC) + 1 : header_end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise SystemExit("unsupported or malformed backup envelope") from exc
    nonce = encrypted[header_end : header_end + NONCE_SIZE]
    ciphertext = encrypted[header_end + NONCE_SIZE :]
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, header)
    except InvalidTag as exc:
        raise SystemExit("backup authentication failed") from exc
    return source_environment, plaintext


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment", required=True, choices=["LOCAL", "TEST", "CI", "STAGING", "PRODUCTION"]
    )
    parser.add_argument("--backup", required=True)
    parser.add_argument("--checksum", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--key-file")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    backup = Path(args.backup).resolve()
    target = Path(args.target).resolve()
    if backup == target:
        raise SystemExit("backup and restore target must differ")
    encrypted = backup.read_bytes()
    if hashlib.sha256(encrypted).hexdigest() != args.checksum:
        raise SystemExit("checksum verification failed")
    if args.environment == "PRODUCTION" and args.confirm != "RESTORE PRODUCTION VPN-SALE":
        raise SystemExit("production restore requires exact confirmation")
    source_environment, plaintext = decrypt_backup(encrypted, load_key(args.key_file))
    _write_atomic(target, plaintext)
    print(
        json.dumps(
            {
                "status": "PASS",
                "source_environment": source_environment,
                "target_environment": args.environment,
                "target": target.name,
                "plaintext_checksum_sha256": hashlib.sha256(plaintext).hexdigest(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
