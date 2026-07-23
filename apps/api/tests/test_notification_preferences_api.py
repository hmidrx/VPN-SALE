from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from platform_api.identity.models import UserModel
from platform_api.notification_preferences import (
    CustomerNotificationPreferenceModel,
    NotificationPreferenceIdempotencyModel,
    required_customer_id_from_telegram_account,
)

MIGRATION_PATH = Path("apps/api/alembic/versions/0028_customer_notification_prefs.py")


def _migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0028_notifications", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_required_customer_id_from_telegram_account_returns_expected_str() -> None:
    customer_id = "11111111-1111-4111-8111-111111111111"

    assert required_customer_id_from_telegram_account(customer_id) == customer_id


def test_required_customer_id_from_telegram_account_accepts_uuid_identity_string() -> None:
    customer_id = str(uuid4())

    assert UUID(required_customer_id_from_telegram_account(customer_id)) == UUID(customer_id)


def test_required_customer_id_from_telegram_account_null_is_typed_not_found() -> None:
    with pytest.raises(HTTPException) as exc_info:
        required_customer_id_from_telegram_account(None)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "customer_not_found"
    assert "Traceback" not in str(exc_info.value.detail)


def test_notification_customer_id_uses_identity_uuid_type() -> None:
    identity_type = UserModel.__table__.c.id.type
    preference_customer_type = CustomerNotificationPreferenceModel.__table__.c.customer_id.type

    assert isinstance(identity_type, postgresql.UUID)
    assert isinstance(preference_customer_type, postgresql.UUID)
    assert preference_customer_type.as_uuid == identity_type.as_uuid


def test_notification_preference_id_uses_repository_uuid_convention() -> None:
    preference_id_type = CustomerNotificationPreferenceModel.__table__.c.id.type
    idempotency_id_type = NotificationPreferenceIdempotencyModel.__table__.c.id.type

    assert isinstance(preference_id_type, postgresql.UUID)
    assert isinstance(idempotency_id_type, postgresql.UUID)
    assert preference_id_type.as_uuid is False
    assert idempotency_id_type.as_uuid is False


def test_postgresql_create_table_foreign_key_uses_uuid_not_varchar() -> None:
    table = cast(Table, CustomerNotificationPreferenceModel.__table__)
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))

    assert "customer_id UUID NOT NULL" in ddl
    assert "FOREIGN KEY(customer_id) REFERENCES identity_users (id) ON DELETE RESTRICT" in ddl
    assert "customer_id VARCHAR" not in ddl


def test_migration_uses_postgresql_uuid_for_customer_foreign_key() -> None:
    migration = _migration_module()

    uuid_type = cast(postgresql.UUID[str], migration.UUID_T)
    assert isinstance(uuid_type, postgresql.UUID)
    assert uuid_type.as_uuid is False
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'sa.Column("customer_id", UUID_T, nullable=False)' in source
    assert 'sa.Column("customer_id", sa.String' not in source


def test_duplicate_preference_rows_are_rejected_by_unique_customer_constraint() -> None:
    table = cast(Table, CustomerNotificationPreferenceModel.__table__)
    constraints = {c.name for c in table.constraints if isinstance(c, UniqueConstraint)}

    assert "uq_customer_notification_preferences_customer" in constraints
