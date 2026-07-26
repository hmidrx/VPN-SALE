from platform_api.database import sync_database_url


def test_sync_database_url_selects_explicit_drivers_without_rewriting_url_data() -> None:
    suffix = "user:p%40ss@db:5432/app%2Fname?sslmode=require&application_name=a%20b"
    assert sync_database_url(f"postgresql+asyncpg://{suffix}") == (f"postgresql+psycopg://{suffix}")
    assert sync_database_url(f"postgresql://{suffix}") == f"postgresql+psycopg://{suffix}"
    assert sync_database_url(f"postgres://{suffix}") == f"postgresql+psycopg://{suffix}"
    assert sync_database_url(f"postgresql+psycopg://{suffix}") == (f"postgresql+psycopg://{suffix}")


def test_sync_database_url_preserves_sqlite_compatibility() -> None:
    assert sync_database_url("sqlite+aiosqlite:///tmp/a%20b.db?mode=ro") == (
        "sqlite:///tmp/a%20b.db?mode=ro"
    )
    assert sync_database_url("sqlite:///:memory:") == "sqlite:///:memory:"


def test_sync_database_url_leaves_unknown_and_malformed_schemes_unchanged() -> None:
    assert sync_database_url("mysql+pymysql://user@db/name") == "mysql+pymysql://user@db/name"
    assert sync_database_url("not-a-url") == "not-a-url"
