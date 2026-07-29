from __future__ import annotations

import ast
from pathlib import Path

REVISION = Path(__file__).parents[1] / "alembic" / "versions" / "0032_manual_card_topups.py"


def test_revision_is_self_contained_and_does_not_pollute_application_metadata() -> None:
    source = REVISION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any(name == "platform_api" or name.startswith("platform_api.") for name in imports)

    compact = source.lower().replace(" ", "")
    forbidden = (
        "__table__",
        "create_all",
        ".create(",
        ".drop(",
        "checkfirst",
        "ifnotexists",
        "identitybase",
    )
    assert all(token not in compact for token in forbidden)


def test_revision_uses_explicit_ordered_schema_operations() -> None:
    source = REVISION.read_text(encoding="utf-8")
    request_create = source.index('op.create_table(\n        "manual_topup_requests"')
    receipt_create = source.index('op.create_table(\n        "manual_topup_receipts"')
    cyclic_fk = source.index('op.create_foreign_key(\n        "fk_manual_topup_current_receipt"')
    assert request_create < receipt_create < cyclic_fk
    assert source.index(
        'op.drop_constraint(\n        "fk_manual_topup_current_receipt"'
    ) < source.index('op.drop_table("manual_topup_receipts")')
