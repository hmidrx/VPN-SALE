from datetime import timedelta
from inspect import getsource

from platform_worker import manual_topup_delivery as delivery
from platform_worker.manual_topup_delivery import MAX_ATTEMPTS, retry_delay


def test_bounded_exponential_retry_policy() -> None:
    assert retry_delay(1) == timedelta(seconds=30)
    assert retry_delay(4) == timedelta(seconds=240)
    assert retry_delay(MAX_ATTEMPTS + 10) == timedelta(seconds=3600)


def test_worker_source_has_safe_claiming_and_no_sensitive_logging() -> None:
    source = getsource(delivery)
    assert "skip_locked=True" in source
    assert "with self.factory.begin() as db" in source
    log = source[source.index("def _log") :]
    for forbidden in ("message.body", "telegram_bot_token", "storage_key", "sanitized_sha256"):
        assert forbidden not in log
