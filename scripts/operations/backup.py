from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment", required=True, choices=["LOCAL", "TEST", "CI", "STAGING", "PRODUCTION"]
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    payload = Path(args.source).read_bytes()
    encrypted = bytes(b ^ 0xA5 for b in payload)
    dest = Path(args.destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(encrypted)
    manifest = {
        "environment": args.environment,
        "completed_at": datetime.now(UTC).isoformat(),
        "checksum_sha256": hashlib.sha256(encrypted).hexdigest(),
        "encrypted_object_reference": dest.name,
        "retention_class": "standard",
    }
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
