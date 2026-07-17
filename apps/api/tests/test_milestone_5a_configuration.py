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
