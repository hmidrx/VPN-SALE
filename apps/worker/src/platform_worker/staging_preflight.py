from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from panel_adapters.sanaei_3x_ui_v370 import SANAEI_3X_UI_V370_CONTRACT
from panel_adapters.vault import ProviderCredentialVault
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from vpnsale_domain.providers import ProviderCertificationStatus, ProviderKind

from platform_api.database import sync_database_url
from platform_api.provider_runtime_models import (
    PanelCredentialModel,
    PanelInstanceModel,
    ProviderConnectionTestModel,
)
from platform_api.service_models import AllocationPolicyVersionModel, AllocationTargetModel


class StagingPreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagingProviderReadiness:
    eligible_targets: int
    active_bindings: int
    certified_panels: int
    aead_credentials: int

    @property
    def ready(self) -> bool:
        return all(
            value > 0
            for value in (
                self.eligible_targets,
                self.active_bindings,
                self.certified_panels,
                self.aead_credentials,
            )
        )


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def validate_staging_environment(environ: Mapping[str, str]) -> None:
    if (environ.get("VPN_SALE_ENVIRONMENT") or "").strip().lower() != "staging":
        raise StagingPreflightError("provider staging preflight requires staging environment")
    if not _is_true(environ.get("VPN_SALE_PROVIDER_WRITES_ENABLED")):
        raise StagingPreflightError("provider staging preflight requires explicit provider writes")
    if _is_true(environ.get("VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED")):
        raise StagingPreflightError("fake customer auth must stay disabled in provider staging")
    if _is_true(environ.get("VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED")):
        raise StagingPreflightError("fake payment success must stay disabled in provider staging")
    if not _is_true(environ.get("VPN_SALE_BOT_ENABLED")):
        raise StagingPreflightError("Telegram bot must be enabled in provider staging")
    if (environ.get("VPN_SALE_BOT_MODE") or "").strip().lower() != "polling":
        raise StagingPreflightError("Telegram bot must use polling in provider staging")
    if not (environ.get("VPN_SALE_TELEGRAM_BOT_TOKEN") or "").strip():
        raise StagingPreflightError("Telegram bot token is required in provider staging")
    if not (environ.get("PROVIDER_VAULT_MASTER_KEY_B64") or "").strip():
        raise StagingPreflightError("provider vault key is required in provider staging")


def collect_staging_provider_readiness(
    factory: sessionmaker[Session],
) -> StagingProviderReadiness:
    provider_kind = ProviderKind.SANAEI_3X_UI.value
    contract = SANAEI_3X_UI_V370_CONTRACT
    valid_versions = {contract.release_tag, contract.release_tag.lstrip("v")}

    with factory() as db:
        eligible_targets = int(
            db.scalar(
                select(func.count())
                .select_from(AllocationTargetModel)
                .where(
                    AllocationTargetModel.provider_kind == provider_kind,
                    AllocationTargetModel.status.in_(("ACTIVE", "ENABLED")),
                    AllocationTargetModel.required_protocol.in_(("vless", "vmess")),
                    AllocationTargetModel.max_capacity > AllocationTargetModel.safety_reserve,
                )
            )
            or 0
        )
        active_bindings = int(
            db.scalar(
                select(func.count())
                .select_from(AllocationPolicyVersionModel)
                .where(
                    AllocationPolicyVersionModel.status == "PUBLISHED",
                )
            )
            or 0
        )
        certified_panels = int(
            db.scalar(
                select(func.count(func.distinct(ProviderConnectionTestModel.panel_instance_id)))
                .select_from(ProviderConnectionTestModel)
                .join(
                    PanelInstanceModel,
                    PanelInstanceModel.id == ProviderConnectionTestModel.panel_instance_id,
                )
                .where(
                    PanelInstanceModel.provider_kind == provider_kind,
                    PanelInstanceModel.status.in_(("ACTIVE", "ENABLED", "enabled")),
                    ProviderConnectionTestModel.status
                    == ProviderCertificationStatus.CONTRACT_VERIFIED.value,
                    ProviderConnectionTestModel.detected_version.in_(valid_versions),
                    ProviderConnectionTestModel.contract_digest == contract.contract_digest,
                )
            )
            or 0
        )
        aead_credentials = int(
            db.scalar(
                select(func.count(func.distinct(PanelCredentialModel.panel_instance_id)))
                .select_from(PanelCredentialModel)
                .join(
                    PanelInstanceModel,
                    PanelInstanceModel.id == PanelCredentialModel.panel_instance_id,
                )
                .where(
                    PanelInstanceModel.provider_kind == provider_kind,
                    PanelInstanceModel.status.in_(("ACTIVE", "ENABLED", "enabled")),
                    PanelCredentialModel.key_version.like("aead-%"),
                )
            )
            or 0
        )
    return StagingProviderReadiness(
        eligible_targets=eligible_targets,
        active_bindings=active_bindings,
        certified_panels=certified_panels,
        aead_credentials=aead_credentials,
    )


def main() -> None:
    validate_staging_environment(os.environ)
    ProviderCredentialVault.from_environment()
    database_url = os.environ.get("VPN_SALE_DATABASE_URL")
    if not database_url:
        raise StagingPreflightError("database URL is required in provider staging")
    engine = create_engine(sync_database_url(database_url), pool_pre_ping=True)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    report = collect_staging_provider_readiness(factory)
    if not report.ready:
        raise StagingPreflightError(
            "certified Sanaei staging configuration is incomplete; inspect admin configuration"
        )
    print(
        "provider_staging_preflight_ok "
        f"eligible_targets={report.eligible_targets} "
        f"active_bindings={report.active_bindings} "
        f"certified_panels={report.certified_panels} "
        f"aead_credentials={report.aead_credentials}",
        flush=True,
    )


if __name__ == "__main__":
    main()
