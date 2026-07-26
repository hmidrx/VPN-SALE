from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from platform_api.admin_auth.service import AdminAuthService
from platform_api.config import get_settings
from platform_api.database import sync_database_url
from platform_api.identity.security import (
    Argon2idPasswordHasher,
    deterministic_development_fernet_key,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m platform_api.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    boot = sub.add_parser("bootstrap-admin")
    boot.add_argument("--email", required=True)
    boot.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.identity_encryption_key:
        settings.identity_encryption_key = deterministic_development_fernet_key()
    password = (
        sys.stdin.readline().rstrip("\n")
        if args.password_stdin
        else getpass.getpass("Admin password: ")
    )
    engine = create_engine(sync_database_url(settings.database_url))
    try:
        with Session(engine) as session, session.begin():
            svc = AdminAuthService(
                session,
                settings,
                Argon2idPasswordHasher(
                    settings.password_argon2_time_cost,
                    settings.password_argon2_memory_cost,
                    settings.password_argon2_parallelism,
                ),
            )
            admin_id = svc.bootstrap_admin(args.email, password)
        print(f"Super Admin bootstrapped: {admin_id}")
        return 0
    except Exception as exc:
        print(f"Bootstrap rejected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
