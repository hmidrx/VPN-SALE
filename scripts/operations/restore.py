from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment", required=True, choices=["LOCAL", "TEST", "CI", "STAGING", "PRODUCTION"]
    )
    parser.add_argument("--backup", required=True)
    parser.add_argument("--checksum", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    encrypted = Path(args.backup).read_bytes()
    if hashlib.sha256(encrypted).hexdigest() != args.checksum:
        raise SystemExit("checksum verification failed")
    if args.environment == "PRODUCTION" and args.confirm != "RESTORE PRODUCTION VPN-SALE":
        raise SystemExit("production restore requires exact confirmation")
    Path(args.target).write_bytes(bytes(b ^ 0xA5 for b in encrypted))
    print(
        json.dumps(
            {"status": "PASS", "environment": args.environment, "target": Path(args.target).name},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
