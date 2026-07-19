from __future__ import annotations

from urllib.parse import quote, unquote, urlparse


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
