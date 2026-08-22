from pathlib import Path

from vpnsale_domain.configuration import SAFE_ACTIONS, compiled_defaults, validate_snapshot


def test_runtime_defaults_expose_no_private_fields() -> None:
    snapshot = compiled_defaults()
    assert validate_snapshot(snapshot).ok
    assert "draft" not in str(snapshot).lower()
    assert "preview" not in str(snapshot).lower()
    assert "OPEN_SUPPORT" not in SAFE_ACTIONS


def test_migration_revision_is_single_head_candidate() -> None:
    revision = Path("apps/api/alembic/versions/0011_milestone_5a_config.py").read_text()
    assert 'down_revision: str = "0010_milestone_4a2b2_recovery"' in revision
    assert "configuration_drafts" in revision
    assert "media_assets" in revision
    assert "configuration.publish" in revision


def test_runtime_defaults_use_accessible_premium_theme() -> None:
    snapshot = compiled_defaults()
    assert snapshot["brand"]["short_name"] == "VPN-SALE"
    assert snapshot["theme"]["dark"]["page_color"] == "#0b0f17"
    assert snapshot["theme"]["light"]["surface_color"] == "#ffffff"
    assert validate_snapshot(snapshot).ok


def test_configuration_api_uses_canonical_etags_and_persisted_previews() -> None:
    source = Path("apps/api/src/platform_api/configuration.py").read_text()
    assert "sort_keys=True" in source
    assert "ConfigurationPreviewSessionModel(" in source
    assert "opaque_reference_hash=_token_hash(token)" in source
    assert "target.version + 1" not in source


def test_private_telegram_runtime_projection_is_safe_and_no_store() -> None:
    source = Path("apps/api/src/platform_api/telegram_internal.py").read_text()
    assert '@router.get("/runtime-configuration")' in source
    assert '"telegram_menu": snapshot["telegram_menu"]' in source
    assert "_no_store(response)" in source
    assert (
        "provider"
        not in source[
            source.index('@router.get("/runtime-configuration")') : source.index("def _account")
        ]
    )
