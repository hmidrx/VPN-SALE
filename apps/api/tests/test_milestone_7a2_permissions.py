from __future__ import annotations

from pathlib import Path


def test_milestone_7a2_quality_permissions_are_granular() -> None:
    seed_source = Path("apps/api/src/platform_api/identity/rbac_seed.py").read_text()
    required = {
        "quality.read",
        "quality.performance.read",
        "quality.performance.execute",
        "quality.security.read",
        "quality.security.execute",
        "quality.chaos.read",
        "quality.chaos.execute",
        "quality.defects.read",
        "quality.defects.manage",
        "releases.candidates.read",
        "releases.candidates.manage",
        "releases.gates.review",
        "releases.go_no_go.read",
        "releases.go_no_go.review",
    }
    for code in required:
        assert f'"{code}"' in seed_source
    assert seed_source.index('"quality.security.execute"') < seed_source.index(
        '"quality.defects.manage"'
    )
