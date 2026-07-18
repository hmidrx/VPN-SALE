from __future__ import annotations

from pathlib import Path


def test_production_release_permissions_are_granular() -> None:
    seed_source = Path("apps/api/src/platform_api/identity/rbac_seed.py").read_text()
    required = (
        "production_releases.read",
        "production_releases.manage",
        "production_releases.request",
        "production_releases.approve",
        "production_releases.deploy",
        "production_releases.start_canary",
        "production_releases.advance",
        "production_releases.pause",
        "production_releases.resume",
        "production_releases.rollback",
        "production_releases.manage_cohorts",
        "production_releases.manage_hypercare",
        "production_releases.review_completion",
    )
    for permission in required:
        assert f'"{permission}"' in seed_source
    assert seed_source.index('"production_releases.read"') < seed_source.index(
        '"production_releases.deploy"'
    )
    assert seed_source.index('"production_releases.manage"') < seed_source.index(
        '"production_releases.approve"'
    )


def test_production_operator_workflow_is_opt_in_and_protected() -> None:
    workflow = Path(".github/workflows/production-release-operator.yml").read_text()
    assert "workflow_dispatch" in workflow
    assert "environment: production" in workflow
    assert "typed_confirmation" in workflow
    assert "No production secrets are requested" in workflow
    assert "exit 1" in workflow
    assert "pull_request" not in workflow
    assert "push:" not in workflow


def test_production_rollout_migration_has_single_head_and_permissions() -> None:
    migration = Path("apps/api/alembic/versions/0027_m7b_prod_rollout.py").read_text()
    assert 'revision: str = "0027_m7b_prod_rollout"' in migration
    assert 'down_revision: str = "0026_m7a2_quality_release"' in migration
    assert "uuid.UUID(" in migration
    assert 'bindparam("code", type_=sa.String())' in migration
    assert "production_release_reports" in migration
    assert "production_release_cohorts" in migration
    assert "production_release_health_evaluations" in migration
