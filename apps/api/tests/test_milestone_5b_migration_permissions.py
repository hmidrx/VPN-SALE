from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import BindParameter

MIGRATION_PATH = Path("apps/api/alembic/versions/0012_milestone_5b_customers.py")


def _migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0012", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_permission_grant_bindparam_uses_postgresql_uuid() -> None:
    migration = _migration_module()
    statement = migration._super_admin_permission_grant_statement()

    bindparams = cast(Mapping[str, BindParameter[object]], statement._bindparams)
    bind = bindparams["permission_id"]
    bind_type = cast(postgresql.UUID[UUID], bind.type)
    assert isinstance(bind_type, postgresql.UUID)
    assert bind_type.as_uuid is True
    compiled_sql = str(statement.compile(dialect=postgresql.dialect()))
    assert ":permission_id" in str(statement)
    assert "::UUID" in compiled_sql
    assert "::VARCHAR" not in compiled_sql


def test_milestone_5b_permission_ids_are_stable_uuid_values() -> None:
    migration = _migration_module()
    permission_ids = [pid for _, _, pid in migration.PERMISSIONS]

    assert all(isinstance(pid, UUID) for pid in permission_ids)
    assert len(permission_ids) == len(set(permission_ids))
    assert len(permission_ids) == 16


def test_seed_permissions_passes_uuid_values_to_super_admin_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _migration_module()
    executions: list[tuple[object, Mapping[str, object] | None]] = []

    class FakeConnection:
        def execute(
            self, statement: object, parameters: Mapping[str, object] | None = None
        ) -> None:
            executions.append((statement, parameters))

    monkeypatch.setattr(migration.op, "get_bind", lambda: FakeConnection())

    migration._seed_permissions()

    grant_parameters: list[Mapping[str, object]] = [
        params for _, params in executions if params is not None
    ]
    assert len(grant_parameters) == len(migration.PERMISSIONS)
    assert all(isinstance(params["permission_id"], UUID) for params in grant_parameters)
    assert {params["permission_id"] for params in grant_parameters} == {
        pid for _, _, pid in migration.PERMISSIONS
    }


def test_milestone_5b_migration_avoids_string_uuid_permission_grants() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "str(pid)" not in source
    assert 'bindparam("permission_id", type_=uuid_type)' in source
    assert "on conflict do nothing" in source.casefold()
