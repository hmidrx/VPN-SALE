from datetime import timedelta
from inspect import getsource

from platform_worker import order_fulfillment
from platform_worker.order_fulfillment import BLOCKED_RETRY, retry_delay


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
