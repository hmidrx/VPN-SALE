from __future__ import annotations

from pathlib import Path

from platform_api.catalog_models import ProductVersionModel


def test_catalog_models_avoid_provider_specific_fields() -> None:
    forbidden = {"panel_url", "credential", "server_ip", "inbound_id", "sanaei", "pasarguard"}
    text = Path("apps/api/src/platform_api/catalog_models.py").read_text().casefold()
    assert not any(term in text for term in forbidden)


def test_product_version_snapshots_are_separate_from_product_table() -> None:
    assert ProductVersionModel.__tablename__ == "product_versions"
    assert "definition_snapshot" in ProductVersionModel.__table__.columns
