from __future__ import annotations

import ast
from pathlib import Path

from platform_api import wallet

CUSTOMER_ADMIN = Path("apps/api/src/platform_api/customer_admin.py")


def test_customer_admin_uses_public_wallet_boundary() -> None:
    tree = ast.parse(CUSTOMER_ADMIN.read_text(encoding="utf-8"))
    private_wallet_imports: list[str] = []
    public_wallet_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "platform_api.wallet":
            for alias in node.names:
                if alias.name.startswith("_"):
                    private_wallet_imports.append(alias.name)
                public_wallet_imports.add(alias.name)

    assert private_wallet_imports == []
    assert {
        "ensure_customer_wallet",
        "build_wallet_admin_view",
        "post_admin_wallet_adjustment",
    }.issubset(public_wallet_imports)


def test_wallet_public_boundary_is_explicitly_typed() -> None:
    assert wallet.ensure_customer_wallet.__annotations__["customer_id"] == "str"
    assert wallet.ensure_customer_wallet.__annotations__["return"] == "WalletModel"
    assert wallet.build_wallet_admin_view.__annotations__["return"] == "dict[str, object]"
    assert wallet.post_admin_wallet_adjustment.__annotations__["return"] == "JournalEntryModel"
