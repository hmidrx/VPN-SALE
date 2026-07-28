from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[4]
ALEMBIC = ROOT / "apps/api/alembic.ini"
REVISION_LINE = re.compile(r"(?m)^([0-9]{4}_[a-z0-9_]+)\b")


def _run(*args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed interpreter and CI-controlled arguments
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC), *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _database_url() -> str:
    return os.environ["VPN_SALE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


def _revision_ids(output: str) -> list[str]:
    """Extract machine revision tokens without relying on Alembic's status decoration."""
    return REVISION_LINE.findall(output)


@pytest.mark.skipif(
    os.environ.get("VPN_SALE_RUN_MIGRATION_LIFECYCLE_TEST") != "1",
    reason="destructive PostgreSQL lifecycle runs only in guarded backend CI",
)
def test_telegram_link_challenge_migration_lifecycle_preserves_identity_ownership() -> None:
    assert os.environ.get("VPN_SALE_ENVIRONMENT") == "test"
    assert os.environ.get("POSTGRES_DB", "").endswith("_test")
    user_id, telegram_id = str(uuid4()), 7_000_000_001
    user_created = False
    try:
        _run("downgrade", "0029_unified_account_schema")
        with psycopg.connect(_database_url(), autocommit=True) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.telegram_link_challenges')"
            ).fetchone() == (None,)
            connection.execute(
                "INSERT INTO identity_users (id,status,created_at,updated_at) "
                "VALUES (%s,'ACTIVE',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                (user_id,),
            )
            user_created = True
            connection.execute(
                "INSERT INTO telegram_accounts "
                "(id,telegram_user_id,user_id,first_seen_at,last_seen_at,bot_started,blocked_bot) "
                "VALUES (%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,false,false)",
                (str(uuid4()), telegram_id, user_id),
            )

        _run("upgrade", "head")
        repository_heads = _revision_ids(_run("heads"))
        assert len(repository_heads) == 1
        current_revisions = _revision_ids(_run("current"))
        assert current_revisions == repository_heads
        _run("upgrade", "head")
        with psycopg.connect(_database_url(), autocommit=True) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.telegram_link_challenges')"
            ).fetchone() == ("telegram_link_challenges",)
            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT indexname FROM pg_indexes WHERE tablename='telegram_link_challenges'"
                ).fetchall()
            }
            assert {
                "ix_telegram_link_challenges_user_active",
                "ix_telegram_link_challenges_expires_at",
            } <= indexes

        _run("downgrade", "0029_unified_account_schema")
        with psycopg.connect(_database_url(), autocommit=True) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.telegram_link_challenges')"
            ).fetchone() == (None,)
            assert connection.execute(
                "SELECT user_id::text FROM telegram_accounts WHERE telegram_user_id=%s",
                (telegram_id,),
            ).fetchone() == (user_id,)
        _run("upgrade", "head")
        with psycopg.connect(_database_url(), autocommit=True) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.telegram_link_challenges')"
            ).fetchone() == ("telegram_link_challenges",)
    finally:
        active_failure = sys.exception()
        cleanup_errors: list[Exception] = []
        if user_created:
            try:
                with psycopg.connect(_database_url(), autocommit=True) as connection:
                    connection.execute(
                        "DELETE FROM telegram_accounts WHERE telegram_user_id=%s", (telegram_id,)
                    )
                    connection.execute("DELETE FROM identity_users WHERE id=%s", (user_id,))
            except Exception as exc:  # noqa: BLE001 - preserve the primary lifecycle failure
                cleanup_errors.append(exc)
        try:
            _run("upgrade", "head")
        except Exception as exc:  # noqa: BLE001 - preserve the primary lifecycle failure
            cleanup_errors.append(exc)
        if cleanup_errors:
            summary = ", ".join(error.__class__.__name__ for error in cleanup_errors)
            if active_failure is not None:
                active_failure.add_note(f"Migration-test cleanup also failed: {summary}")
            else:
                raise cleanup_errors[0]
