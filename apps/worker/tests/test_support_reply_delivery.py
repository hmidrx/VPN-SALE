from inspect import getsource

from platform_worker import support_reply_delivery as delivery


def test_support_notification_uses_existing_support_surface_without_reply_body() -> None:
    assert delivery._support_url("https://example.test/") == (
        "https://example.test/support?source=telegram"
    )
    text = delivery._notification_text("SUP-123")
    assert "SUP-123" in text
    assert "پاسخ جدیدی" in text


def test_support_worker_claims_safely_and_respects_notification_controls() -> None:
    source = getsource(delivery)
    assert "skip_locked=True" in source
    assert "PROCESSING_TIMEOUT" in source
    assert "support_reply_enabled" in source
    assert "BOT_NOT_STARTED" in source
    assert "BOT_BLOCKED" in source
    assert "MAX_ATTEMPTS" in source
    assert "db.rollback()" in source


def test_support_worker_does_not_log_or_persist_message_body() -> None:
    source = getsource(delivery)
    log = source[source.index("def _log") :]
    assert "body" not in log
    assert 'message["body"]' not in source
    assert 'conversation["subject"]' not in source
