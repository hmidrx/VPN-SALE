from __future__ import annotations

from collections.abc import Callable, Iterator
from types import SimpleNamespace

import pytest

import platform_api.management as management
from platform_api.database import get_db_session
from platform_api.main import app
from platform_api.management import current_admin

AdminAuthorizer = Callable[[set[str] | None], None]


class _TestSession:
    def add(self, _row: object) -> None:
        pass


@pytest.fixture(name="admin_authorizer")
def _admin_authorizer(monkeypatch: pytest.MonkeyPatch) -> Iterator[AdminAuthorizer]:
    """Switch a route test between anonymous, forbidden, and permitted admin states."""

    original_overrides = dict(app.dependency_overrides)
    active_permissions: set[str] = set()
    app.dependency_overrides[get_db_session] = _TestSession
    monkeypatch.setattr(
        management,
        "_active_permissions",
        lambda _db, _admin_id: set(active_permissions),
    )

    def authorize(permissions: set[str] | None) -> None:
        active_permissions.clear()
        if permissions is None:
            app.dependency_overrides.pop(current_admin, None)
            return
        active_permissions.update(permissions)
        app.dependency_overrides[current_admin] = lambda: SimpleNamespace(id="test-admin")

    try:
        yield authorize
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
