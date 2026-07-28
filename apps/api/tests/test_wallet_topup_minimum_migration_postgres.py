from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[3]
ALEMBIC = ROOT / "apps/api/alembic.ini"
LEGACY_MINIMUM_RIAL = 100_000
MINIMUM_RIAL = 1_000_000
UNCHANGED_MAXIMUM_TOPUP_RIAL = 777_000_000
UNCHANGED_MAXIMUM_BALANCE_RIAL = 888_000_000
UNCHANGED_HISTORY_PAGE_SIZE = 37


def _run(*args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and CI-controlled arguments
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC), *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _database_url() -> str:
    return os.environ["VPN_SALE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


def _policy(connection: psycopg.Connection[tuple[Any, ...]]) -> tuple[int, int, int, int]:
    row = connection.execute(
        "SELECT minimum_topup_amount_rial, maximum_topup_amount_rial, "
        "maximum_wallet_balance_rial, max_transaction_history_page_size "
        "FROM wallet_policies WHERE currency='IRR'"
    ).fetchone()
    assert row is not None
    return cast(tuple[int, int, int, int], tuple(int(value) for value in row))


@pytest.mark.skipif(
    os.environ.get("VPN_SALE_RUN_MIGRATION_LIFECYCLE_TEST") != "1",
    reason="destructive PostgreSQL lifecycle runs only in guarded backend CI",
)
def test_wallet_topup_minimum_migration_round_trip_is_idempotent() -> None:
    assert os.environ.get("VPN_SALE_ENVIRONMENT") == "test"
    assert os.environ.get("POSTGRES_DB", "").endswith("_test")
    assert MINIMUM_RIAL % 10 == 0
    assert MINIMUM_RIAL // 10 == 100_000

    original: tuple[int, int, int, int] | None = None
    try:
        _run("upgrade", "head")
        with psycopg.connect(_database_url(), autocommit=True) as connection:
            original = _policy(connection)
            connection.execute(
                "UPDATE wallet_policies SET minimum_topup_amount_rial=%s, "
                "maximum_topup_amount_rial=%s, maximum_wallet_balance_rial=%s, "
                "max_transaction_history_page_size=%s WHERE currency='IRR'",
                (
                    LEGACY_MINIMUM_RIAL,
                    UNCHANGED_MAXIMUM_TOPUP_RIAL,
                    UNCHANGED_MAXIMUM_BALANCE_RIAL,
                    UNCHANGED_HISTORY_PAGE_SIZE,
                ),
            )

        _run("downgrade", "0030_telegram_link_challenges")
        _run("upgrade", "head")
        with psycopg.connect(_database_url(), autocommit=True) as connection:
            assert _policy(connection) == (
                MINIMUM_RIAL,
                UNCHANGED_MAXIMUM_TOPUP_RIAL,
                UNCHANGED_MAXIMUM_BALANCE_RIAL,
                UNCHANGED_HISTORY_PAGE_SIZE,
            )

        _run("downgrade", "0030_telegram_link_challenges")
        with psycopg.connect(_database_url(), autocommit=True) as connection:
            assert _policy(connection) == (
                LEGACY_MINIMUM_RIAL,
                UNCHANGED_MAXIMUM_TOPUP_RIAL,
                UNCHANGED_MAXIMUM_BALANCE_RIAL,
                UNCHANGED_HISTORY_PAGE_SIZE,
            )

        _run("upgrade", "head")
        _run("upgrade", "head")
        with psycopg.connect(_database_url(), autocommit=True) as connection:
            assert _policy(connection) == (
                MINIMUM_RIAL,
                UNCHANGED_MAXIMUM_TOPUP_RIAL,
                UNCHANGED_MAXIMUM_BALANCE_RIAL,
                UNCHANGED_HISTORY_PAGE_SIZE,
            )
    finally:
        _run("upgrade", "head")
        if original is not None:
            with psycopg.connect(_database_url(), autocommit=True) as connection:
                connection.execute(
                    "UPDATE wallet_policies SET minimum_topup_amount_rial=%s, "
                    "maximum_topup_amount_rial=%s, maximum_wallet_balance_rial=%s, "
                    "max_transaction_history_page_size=%s WHERE currency='IRR'",
                    original,
                )
