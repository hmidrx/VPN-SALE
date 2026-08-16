from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote, urlparse

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_database_url_encodes_reserved_password_and_decodes_without_leak() -> None:
    raw = "Yaghii@@118"
    encoded = quote(raw, safe="")
    url = f"postgresql+asyncpg://vpnsale:{encoded}@postgres:5432/vpnsale"
    assert "@@" not in urlparse(url).netloc
    assert unquote(urlparse(url).password or "") == raw


def test_alembic_configparser_percent_escape() -> None:
    raw = "Yaghii@@118"
    url = f"postgresql+asyncpg://vpnsale:{quote(raw, safe='')}@postgres:5432/vpnsale"
    assert "%40%40" in url
    assert url.replace("%", "%%").count("%%40") == 2


def test_private_media_is_persistent_and_test_server_support_media_is_isolated() -> None:
    base_compose = (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    test_compose = (_REPO_ROOT / "docker-compose.test-server.yml").read_text(encoding="utf-8")
    api_dockerfile = (_REPO_ROOT / "infra/docker/api.Dockerfile").read_text(encoding="utf-8")

    assert "private_media:/var/lib/vpnsale/private" in base_compose
    assert "private_media:" in base_compose
    assert "VPN_SALE_SUPPORT_PRIVATE_UPLOAD_ROOT: /var/lib/vpnsale/private/support" in test_compose
    assert (
        "test_server_support_attachments:/var/lib/vpnsale/private/support" in test_compose
    )
    assert "test_server_support_attachments:" in test_compose
    assert "-m 0700 /var/lib/vpnsale/private/support" in api_dockerfile
    assert "test -w /var/lib/vpnsale/private/support" in api_dockerfile
