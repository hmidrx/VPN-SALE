from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import Table, create_engine, inspect, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from platform_api.identity.models import IdentityBase

# Importing the application registers every model that shares IdentityBase metadata.
from platform_api.main import app
from platform_api.manual_topup_models import ManualTopupDestinationVersionModel


def _compiled_ddl(dialect: Dialect) -> str:
    table = ManualTopupDestinationVersionModel.__table__
    assert isinstance(table, Table)
    return str(CreateTable(table).compile(dialect=dialect))


def test_identity_metadata_creates_destination_table_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    assert app is not None

    IdentityBase.metadata.create_all(engine)

    assert "manual_topup_destination_versions" in inspect(engine).get_table_names()


def test_sqlite_ddl_uses_supported_ascii_digit_constraint() -> None:
    ddl = _compiled_ddl(sqlite.dialect())

    assert " ~ " not in ddl
    assert "length(card_last4) = 4" in ddl
    assert "card_last4 GLOB '[0-9][0-9][0-9][0-9]'" in ddl


def test_postgresql_ddl_retains_strict_ascii_digit_constraint() -> None:
    ddl = _compiled_ddl(postgresql.dialect())

    assert "card_last4 ~ '^[0-9]{4}$'" in ddl
    assert "GLOB" not in ddl


@pytest.mark.parametrize("card_last4", ["0123", "9999"])
def test_sqlite_accepts_valid_last_four(card_last4: str) -> None:
    engine = create_engine("sqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO manual_topup_destination_versions "
                "(id, reference, encrypted_card_number, card_last4, encryption_key_version, "
                "created_by_admin_id) VALUES "
                "(:id, :reference, :ciphertext, :card_last4, :key_version, :admin_id)"
            ),
            {
                "id": str(uuid4()),
                "reference": f"synthetic_{uuid4().hex}",
                "ciphertext": "synthetic-ciphertext",
                "card_last4": card_last4,
                "key_version": "test-v1",
                "admin_id": str(uuid4()),
            },
        )


@pytest.mark.parametrize("card_last4", ["123", "12345", "12a4", "۱۲۳۴"])
def test_sqlite_rejects_invalid_last_four(card_last4: str) -> None:
    engine = create_engine("sqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO manual_topup_destination_versions "
                "(id, reference, encrypted_card_number, card_last4, encryption_key_version, "
                "created_by_admin_id) VALUES "
                "(:id, :reference, :ciphertext, :card_last4, :key_version, :admin_id)"
            ),
            {
                "id": str(uuid4()),
                "reference": f"synthetic_{uuid4().hex}",
                "ciphertext": "synthetic-ciphertext",
                "card_last4": card_last4,
                "key_version": "test-v1",
                "admin_id": str(uuid4()),
            },
        )
