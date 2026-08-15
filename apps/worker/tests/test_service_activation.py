from __future__ import annotations

from datetime import timedelta
from inspect import getsource

from platform_worker import real_activator, service_activation
from platform_worker.main import build_service_activator
from platform_worker.real_activator import DatabaseSanaeiActivator
from platform_worker.service_activation import BLOCKED_RETRY, DisabledActivator, retry_delay


def test_activation_retry_is_bounded_and_blocked_work_is_not_hammered() -> None:
    assert retry_delay(1) == timedelta(seconds=15)
    assert retry_delay(100) == timedelta(hours=1)
    assert BLOCKED_RETRY == timedelta(hours=6)


def test_activation_claim_is_postgres_safe_and_provider_io_is_outside_claim() -> None:
    source = getsource(service_activation.ServiceActivationWorker)
    assert "with_for_update(skip_locked=True)" in source
    assert ".limit(MAX_BATCH)" in source
    assert source.index("self.activator.activate") > source.index("def _claim")
    assert "compensate_failed_fulfillment" not in source
    assert "refund" not in source.lower()


def test_provider_activation_is_gated_on_customer_delivery_profile() -> None:
    source = getsource(real_activator.DatabaseSanaeiActivator.activate)
    profile_gate = source.index("load_allocation_delivery_profile")
    render_gate = source.index("render_service_connection")
    provider_call = source.index("self._execute")

    assert profile_gate < provider_call
    assert render_gate < provider_call


def test_production_composition_reaches_real_activator_only_when_writes_enabled() -> None:
    factory = object()
    assert isinstance(build_service_activator(factory, False), DisabledActivator)  # type: ignore[arg-type]
    assert isinstance(build_service_activator(factory, True), DatabaseSanaeiActivator)  # type: ignore[arg-type]


def test_active_transition_is_atomic_with_revision_and_entitlement_clock() -> None:
    source = getsource(service_activation.ServiceActivationWorker._complete_success)
    revision_write = source.index("DeliveryRevisionModel(")
    clock_write = source.index("FulfillmentEntitlementClockModel(")
    lifecycle_write = source.index('service.lifecycle = "ACTIVE"')
    commit = source.rindex("db.commit()")

    assert revision_write < lifecycle_write < commit
    assert clock_write < lifecycle_write < commit
    assert 'attachment.verification_status = "VERIFIED"' in source
    assert '"provider_host_used": False' in source
    assert "credential_fingerprints" in source
