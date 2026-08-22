from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from telegram_bot.application.identity import (
    AccountStatus,
    RegisterOrUpdateTelegramBotUser,
    TelegramIdentityResult,
)
from telegram_bot.internal_api import PrivateApiUnavailable
from telegram_bot.service_management_api import ServiceManagementPrivatePlatformClient

_ALLOWED_SIGNALS = frozenset(
    {
        "WORKER_HEARTBEAT_MISSING",
        "WORKER_HEARTBEAT_STALE",
        "WORKER_CYCLE_FAILURE_STREAK",
        "WORKER_RECENT_CYCLE_FAILURE",
        "OUTBOX_FAILED",
        "OUTBOX_STALE_CLAIMS",
        "OUTBOX_RETRYING",
        "OUTBOX_LAGGING",
        "FULFILLMENT_FAILED",
        "FULFILLMENT_OPERATOR_REVIEW",
        "FULFILLMENT_BLOCKED",
        "FULFILLMENT_RETRYING",
        "SERVICE_OPERATION_REVIEW_REQUIRED",
        "USAGE_SYNC_DEGRADED",
        "USAGE_DATA_STALE",
    }
)


@dataclass(frozen=True)
class OperatorHealth:
    status: str
    signals: tuple[str, ...]
    worker_state: str
    worker_consecutive_failures: int
    worker_last_seen_age_seconds: int | None
    outbox_pending_due: int
    outbox_retrying: int
    outbox_failed: int
    outbox_stale_claims: int
    fulfillment_retry_pending: int
    fulfillment_blocked: int
    fulfillment_operator_review: int
    fulfillment_failed: int
    service_operations_in_progress: int
    service_operations_review_required: int
    usage_latest_status: str
    usage_degraded_runs_last_hour: int
    usage_stale_active_accounts: int


class OperatorPortal(Protocol):
    def operator_health(self, telegram_user_id: int) -> OperatorHealth: ...
    def runtime_configuration(self, telegram_user_id: int) -> dict[str, object]: ...

def _nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PrivateApiUnavailable(f"پاسخ مدیریتی معتبر نیست: {field}")
    return value


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PrivateApiUnavailable(f"پاسخ مدیریتی معتبر نیست: {field}")
    return cast(dict[str, object], value)


class OperatorPrivatePlatformClient(ServiceManagementPrivatePlatformClient, OperatorPortal):
    def register_or_update(
        self, command: RegisterOrUpdateTelegramBotUser
    ) -> TelegramIdentityResult:
        data = self._request(
            "POST",
            "/identity/register-or-resolve",
            command.telegram_user_id,
            {
                "telegram_user_id": command.telegram_user_id,
                "username": command.username,
                "first_name": command.first_name,
                "last_name": command.last_name,
                "language_code": command.language_code,
                "bot_started": command.bot_started,
            },
        )
        return TelegramIdentityResult(
            str(data["customer_reference"]),
            AccountStatus(str(data["account_state"])),
            bool(data["created"]),
            cast(str | None, data.get("locale")),
        )

    def runtime_configuration(self, telegram_user_id: int) -> dict[str, object]:
        data = self._request("GET", "/runtime-configuration", telegram_user_id)
        version = _nonnegative_int(data.get("runtime_version"), "runtime_version")
        brand = _mapping(data.get("brand"), "brand")
        short_name = brand.get("short_name")
        if not isinstance(short_name, str) or not short_name.strip() or len(short_name) > 64:
            raise PrivateApiUnavailable("پاسخ برند معتبر نیست.")
        menu = data.get("telegram_menu")
        if not isinstance(menu, list) or len(menu) > 32:
            raise PrivateApiUnavailable("پاسخ منوی ربات معتبر نیست.")
        checked_menu: list[dict[str, object]] = []
        for raw in cast(list[object], menu):
            item = _mapping(raw, "telegram_menu")
            action = item.get("action")
            labels = _mapping(item.get("label"), "telegram_menu.label")
            if not isinstance(action, str) or len(action) > 64:
                raise PrivateApiUnavailable("پاسخ منوی ربات معتبر نیست.")
            if not all(isinstance(labels.get(locale), str) for locale in ("fa", "en")):
                raise PrivateApiUnavailable("پاسخ برچسب منوی ربات معتبر نیست.")
            checked_menu.append({"action": action, "label": labels})
        welcome = _mapping(data.get("welcome_template"), "welcome_template")
        return {
            "runtime_version": version,
            "brand": {
                "short_name": short_name,
                "store_name": brand.get("store_name"),
                "tagline": brand.get("tagline"),
            },
            "telegram_menu": checked_menu,
            "welcome_template": welcome,
            "maintenance": bool(data.get("maintenance", False)),
        }

    def operator_health(self, telegram_user_id: int) -> OperatorHealth:
        data = self._request("GET", "/operator/health", telegram_user_id)
        status = data.get("status")
        if status not in {"HEALTHY", "DEGRADED", "ACTION_REQUIRED"}:
            raise PrivateApiUnavailable("پاسخ وضعیت مدیریتی معتبر نیست.")

        raw_signals = data.get("signals")
        if not isinstance(raw_signals, list):
            raise PrivateApiUnavailable("پاسخ سیگنال مدیریتی معتبر نیست.")
        checked_signals = cast(list[object], raw_signals)
        if len(checked_signals) > len(_ALLOWED_SIGNALS):
            raise PrivateApiUnavailable("پاسخ سیگنال مدیریتی معتبر نیست.")
        signals: list[str] = []
        for value in checked_signals:
            if not isinstance(value, str) or value not in _ALLOWED_SIGNALS:
                raise PrivateApiUnavailable("پاسخ سیگنال مدیریتی معتبر نیست.")
            signals.append(value)

        worker = _mapping(data.get("worker"), "worker")
        worker_state = worker.get("state")
        if worker_state not in {"RUNNING", "DEGRADED", "STALE", "MISSING"}:
            raise PrivateApiUnavailable("پاسخ وضعیت Worker معتبر نیست.")
        last_seen = worker.get("last_seen_age_seconds")
        if last_seen is not None:
            last_seen = _nonnegative_int(last_seen, "worker_last_seen_age_seconds")

        outbox = _mapping(data.get("outbox"), "outbox")
        fulfillment = _mapping(data.get("fulfillment"), "fulfillment")
        operations = _mapping(data.get("service_operations"), "service_operations")
        usage = _mapping(data.get("usage_sync"), "usage_sync")
        usage_status = usage.get("latest_status")
        if usage_status not in {"SUCCESS", "PARTIAL", "FAILED", "UNKNOWN"}:
            raise PrivateApiUnavailable("پاسخ وضعیت مصرف معتبر نیست.")

        return OperatorHealth(
            status=str(status),
            signals=tuple(signals),
            worker_state=str(worker_state),
            worker_consecutive_failures=_nonnegative_int(
                worker.get("consecutive_failures"), "worker_consecutive_failures"
            ),
            worker_last_seen_age_seconds=last_seen,
            outbox_pending_due=_nonnegative_int(outbox.get("pending_due"), "outbox_pending_due"),
            outbox_retrying=_nonnegative_int(outbox.get("retrying"), "outbox_retrying"),
            outbox_failed=_nonnegative_int(outbox.get("failed"), "outbox_failed"),
            outbox_stale_claims=_nonnegative_int(outbox.get("stale_claims"), "outbox_stale_claims"),
            fulfillment_retry_pending=_nonnegative_int(
                fulfillment.get("retry_pending"), "fulfillment_retry_pending"
            ),
            fulfillment_blocked=_nonnegative_int(fulfillment.get("blocked"), "fulfillment_blocked"),
            fulfillment_operator_review=_nonnegative_int(
                fulfillment.get("operator_review"), "fulfillment_operator_review"
            ),
            fulfillment_failed=_nonnegative_int(fulfillment.get("failed"), "fulfillment_failed"),
            service_operations_in_progress=_nonnegative_int(
                operations.get("in_progress"), "service_operations_in_progress"
            ),
            service_operations_review_required=_nonnegative_int(
                operations.get("review_required"), "service_operations_review_required"
            ),
            usage_latest_status=str(usage_status),
            usage_degraded_runs_last_hour=_nonnegative_int(
                usage.get("degraded_runs_last_hour"), "usage_degraded_runs_last_hour"
            ),
            usage_stale_active_accounts=_nonnegative_int(
                usage.get("stale_active_accounts"), "usage_stale_active_accounts"
            ),
        )
