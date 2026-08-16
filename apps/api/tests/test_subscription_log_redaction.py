from __future__ import annotations

import logging

from platform_api.logging import SubscriptionPathRedactionFilter, redact_subscription_path


def test_subscription_path_redaction_preserves_format_suffix_and_hides_query() -> None:
    token = "A" * 64
    raw = f"/subscriptions/{token}/mihomo?client=secret"

    redacted = redact_subscription_path(raw)

    assert token not in redacted
    assert "secret" not in redacted
    assert redacted == "/subscriptions/[REDACTED]/mihomo?[REDACTED]"


def test_uvicorn_access_record_never_formats_raw_subscription_token() -> None:
    token = "B" * 64
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1234",
            "GET",
            f"/subscriptions/{token}/links?cache=bypass",
            "1.1",
            200,
        ),
        exc_info=None,
    )

    assert SubscriptionPathRedactionFilter().filter(record) is True
    rendered = record.getMessage()

    assert token not in rendered
    assert "bypass" not in rendered
    assert "/subscriptions/[REDACTED]/links?[REDACTED]" in rendered
