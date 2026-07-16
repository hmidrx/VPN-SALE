from urllib.parse import urlsplit

import pytest

from platform_api.config import Settings


def test_ci_database_url_uses_runner_host_database_and_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VPN_SALE_DATABASE_URL",
        "postgresql+asyncpg://vpnsale:ci-placeholder@127.0.0.1:5432/vpnsale_test",
    )
    settings = Settings()

    parsed = urlsplit(settings.database_url)

    assert parsed.hostname == "127.0.0.1"
    assert parsed.path == "/vpnsale_test"
    assert parsed.username == "vpnsale"
    assert "ci-placeholder" not in repr((parsed.hostname, parsed.path, parsed.username))
