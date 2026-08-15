from datetime import timedelta
from inspect import getsource

import pytest
from vpnsale_domain.providers import ProviderError, ProviderErrorCode

from platform_worker import order_fulfillment
from platform_worker.main import build_order_provisioner
from platform_worker.order_fulfillment import BLOCKED_RETRY, DisabledProvisioner, retry_delay
from platform_worker.real_provisioner import DatabaseSanaeiProvisioner


def test_retry_is_bounded_and_blocked_work_is_not_hammered() -> None:
    assert retry_delay(1) == timedelta(seconds=30)
    assert retry_delay(100) == timedelta(hours=1)
    assert BLOCKED_RETRY == timedelta(hours=6)


def test_claiming_is_bounded_postgres_safe_and_external_io_is_outside_claim() -> None:
    source = getsource(order_fulfillment.OrderFulfillmentWorker)
    assert "with_for_update(skip_locked=True)" in source
    assert ".limit(MAX_BATCH)" in source
    assert source.index("def _prepare") > source.index("def _claim")
    assert source.index("self.provisioner.provision") > source.index("def _finish")


def test_remote_identity_and_service_reference_are_deterministic() -> None:
    source = getsource(order_fulfillment.OrderFulfillmentWorker)
    assert 'uuid5(NAMESPACE_URL, f"vpnsale:fulfillment:{order.id}:{item.id}:1")' in source
    assert 'uuid5(NAMESPACE_URL, "service:" + order.id)' in source
    assert "Telegram" not in source


def test_production_composition_reaches_real_provisioner_only_when_enabled() -> None:
    factory = object()
    assert isinstance(build_order_provisioner(factory, False), DisabledProvisioner)  # type: ignore[arg-type]
    assert isinstance(build_order_provisioner(factory, True), DatabaseSanaeiProvisioner)  # type: ignore[arg-type]


def test_expected_vault_failure_is_blocked_but_programming_error_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner = DatabaseSanaeiProvisioner(object(), True)  # type: ignore[arg-type]
    expected = ProviderError(
        ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE, "vault key unavailable"
    )
    monkeypatch.setattr(
        provisioner, "_select", lambda attempt, item: (_ for _ in ()).throw(expected)
    )
    result = provisioner.provision(object(), object(), object())  # type: ignore[arg-type]
    assert result.outcome == "BLOCKED_BY_CONFIGURATION"
    monkeypatch.setattr(
        provisioner, "_select", lambda attempt, item: (_ for _ in ()).throw(AssertionError())
    )
    with pytest.raises(AssertionError):
        provisioner.provision(object(), object(), object())  # type: ignore[arg-type]
