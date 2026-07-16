from __future__ import annotations

import ast
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
ALEMBIC_VERSION_NUM_MAX_LENGTH = 32


def _revision_id(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "revision":
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    raise AssertionError(f"Migration {path.name} does not declare a literal revision ID")


def test_alembic_revision_ids_fit_default_version_table() -> None:
    migrations = sorted(MIGRATIONS_DIR.glob("*.py"))
    assert migrations, "No Alembic migrations were found"

    for migration in migrations:
        revision = _revision_id(migration)
        assert len(revision) <= ALEMBIC_VERSION_NUM_MAX_LENGTH, (
            f"Alembic revision ID {revision!r} in {migration.name} exceeds "
            f"{ALEMBIC_VERSION_NUM_MAX_LENGTH} characters"
        )
