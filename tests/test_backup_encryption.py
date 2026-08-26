from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "scripts" / "operations" / "backup.py"
RESTORE = ROOT / "scripts" / "operations" / "restore.py"


def _environment(key: bytes) -> dict[str, str]:
    environment = dict(os.environ)
    environment["VPN_SALE_BACKUP_MASTER_KEY_B64"] = base64.urlsafe_b64encode(key).decode()
    return environment


@contextmanager
def _runtime_directory() -> Iterator[Path]:
    path = ROOT / f".backup-test-runtime-{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_backup_round_trip_is_authenticated_and_not_plaintext() -> None:
    with _runtime_directory() as runtime:
        _assert_backup_round_trip(runtime)


def _assert_backup_round_trip(runtime: Path) -> None:
    source = runtime / "database.dump"
    encrypted = runtime / "database.dump.aead"
    restored = runtime / "restored.dump"
    payload = b"private-database-fixture\x00panel-credential-ciphertext"
    source.write_bytes(payload)
    result = subprocess.run(  # noqa: S603 -- fixed interpreter and repository script
        [
            sys.executable,
            str(BACKUP),
            "--environment",
            "TEST",
            "--source",
            str(source),
            "--destination",
            str(encrypted),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_environment(b"a" * 32),
    )
    manifest = json.loads(result.stdout)
    envelope = encrypted.read_bytes()
    assert payload not in envelope
    assert manifest["encryption"] == "AES-256-GCM"
    assert manifest["checksum_sha256"] == hashlib.sha256(envelope).hexdigest()

    subprocess.run(  # noqa: S603 -- fixed interpreter and repository script
        [
            sys.executable,
            str(RESTORE),
            "--environment",
            "TEST",
            "--backup",
            str(encrypted),
            "--checksum",
            manifest["checksum_sha256"],
            "--target",
            str(restored),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_environment(b"a" * 32),
    )
    assert restored.read_bytes() == payload


def test_restore_rejects_tampering_wrong_key_and_unconfirmed_production() -> None:
    with _runtime_directory() as runtime:
        _assert_restore_rejections(runtime)


def _assert_restore_rejections(runtime: Path) -> None:
    source = runtime / "source.dump"
    encrypted = runtime / "source.dump.aead"
    target = runtime / "target.dump"
    source.write_bytes(b"authenticated backup")
    result = subprocess.run(  # noqa: S603 -- fixed interpreter and repository script
        [
            sys.executable,
            str(BACKUP),
            "--environment",
            "PRODUCTION",
            "--source",
            str(source),
            "--destination",
            str(encrypted),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_environment(b"b" * 32),
    )
    checksum = json.loads(result.stdout)["checksum_sha256"]
    unconfirmed = subprocess.run(  # noqa: S603 -- fixed interpreter and repository script
        [
            sys.executable,
            str(RESTORE),
            "--environment",
            "PRODUCTION",
            "--backup",
            str(encrypted),
            "--checksum",
            checksum,
            "--target",
            str(target),
        ],
        capture_output=True,
        text=True,
        env=_environment(b"b" * 32),
    )
    assert unconfirmed.returncode != 0
    assert not target.exists()

    wrong_key = subprocess.run(  # noqa: S603 -- fixed interpreter and repository script
        [
            sys.executable,
            str(RESTORE),
            "--environment",
            "TEST",
            "--backup",
            str(encrypted),
            "--checksum",
            checksum,
            "--target",
            str(target),
        ],
        capture_output=True,
        text=True,
        env=_environment(b"c" * 32),
    )
    assert wrong_key.returncode != 0
    assert "authentication failed" in wrong_key.stderr
    assert not target.exists()

    tampered = bytearray(encrypted.read_bytes())
    tampered[-1] ^= 1
    encrypted.write_bytes(tampered)
    tampered_result = subprocess.run(  # noqa: S603 -- fixed interpreter and repository script
        [
            sys.executable,
            str(RESTORE),
            "--environment",
            "TEST",
            "--backup",
            str(encrypted),
            "--checksum",
            hashlib.sha256(tampered).hexdigest(),
            "--target",
            str(target),
        ],
        capture_output=True,
        text=True,
        env=_environment(b"b" * 32),
    )
    assert tampered_result.returncode != 0
    assert "authentication failed" in tampered_result.stderr
    assert not target.exists()
