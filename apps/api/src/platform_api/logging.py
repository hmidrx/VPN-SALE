from __future__ import annotations

import logging
import re
from typing import Any

import structlog

_SUBSCRIPTION_PATH = re.compile(r"(/subscriptions/)[^/?#\s\"]+")


def redact_subscription_path(value: str) -> str:
    """Remove opaque subscription credentials from a loggable URL/path."""
    if "/subscriptions/" not in value:
        return value
    redacted = _SUBSCRIPTION_PATH.sub(r"\1[REDACTED]", value)
    if "?" in redacted:
        redacted = redacted.split("?", 1)[0] + "?[REDACTED]"
    if "#" in redacted:
        redacted = redacted.split("#", 1)[0] + "#[REDACTED]"
    return redacted


class SubscriptionPathRedactionFilter(logging.Filter):
    """Sanitize Uvicorn access records before any formatter sees the request path."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_subscription_path(record.msg)
        args: Any = record.args
        if isinstance(args, tuple):
            record.args = tuple(
                redact_subscription_path(item) if isinstance(item, str) else item for item in args
            )
        elif isinstance(args, dict):
            record.args = {
                key: redact_subscription_path(item) if isinstance(item, str) else item
                for key, item in args.items()
            }
        return True


def _install_subscription_access_log_redaction() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, SubscriptionPathRedactionFilter) for item in logger.filters):
        logger.addFilter(SubscriptionPathRedactionFilter())


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    _install_subscription_access_log_redaction()
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
