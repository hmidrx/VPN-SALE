from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import islice
from typing import Literal, Protocol

from .application.identity import AccountStatus

Page = Literal[
    "profile", "services", "wallet", "security", "support", "education", "status", "privacy", "help"
]


class ConversationKind(StrEnum):
    SUPPORT_CATEGORY = "support_category"
    SUPPORT_SUBJECT = "support_subject"
    SUPPORT_MESSAGE = "support_message"
    PROFILE_DISPLAY_NAME = "profile_display_name"


@dataclass(frozen=True)
class CustomerContext:
    customer_ref: str
    telegram_user_id: int
    locale: str


@dataclass(frozen=True)
class NotificationPreferences:
    service_expiry_enabled: bool = True
    low_traffic_enabled: bool = True
    payment_enabled: bool = True
    support_reply_enabled: bool = True
    announcements_enabled: bool = True

    def with_toggled(self, key: str) -> NotificationPreferences:
        if key not in NOTIFICATION_PREFERENCE_KEYS:
            raise ValueError("unknown notification preference")
        return NotificationPreferences(
            service_expiry_enabled=(
                not self.service_expiry_enabled
                if key == "service_expiry_enabled"
                else self.service_expiry_enabled
            ),
            low_traffic_enabled=(
                not self.low_traffic_enabled
                if key == "low_traffic_enabled"
                else self.low_traffic_enabled
            ),
            payment_enabled=(
                not self.payment_enabled if key == "payment_enabled" else self.payment_enabled
            ),
            support_reply_enabled=(
                not self.support_reply_enabled
                if key == "support_reply_enabled"
                else self.support_reply_enabled
            ),
            announcements_enabled=(
                not self.announcements_enabled
                if key == "announcements_enabled"
                else self.announcements_enabled
            ),
        )


NOTIFICATION_PREFERENCE_KEYS = frozenset(
    {
        "service_expiry_enabled",
        "low_traffic_enabled",
        "payment_enabled",
        "support_reply_enabled",
        "announcements_enabled",
    }
)


@dataclass(frozen=True)
class CustomerProfile:
    display_name: str
    telegram_linked: bool
    account_state: AccountStatus
    created_at: datetime
    language: str
    username: str | None = None


@dataclass(frozen=True)
class ServiceSummary:
    ref: str
    owner_ref: str
    plan_name: str
    status: str
    expires_at: datetime | None
    remaining_gb: int | None
    total_gb: int | None
    location: str | None
    renewable: bool
    sensitive_preview: str = "برای نمایش اطلاعات حساس، دکمه نمایش اشتراک را بزنید."


@dataclass(frozen=True)
class WalletTransaction:
    ref: str
    amount_minor: int
    currency: str
    status: str
    transaction_type: str
    created_at: datetime


@dataclass(frozen=True)
class ManualTopup:
    reference: str
    amount_toman: int
    status: str
    created_at: datetime
    submitted_at: datetime | None = None
    verified_amount_toman: int | None = None
    bonus_amount_toman: int | None = None
    total_credited_toman: int | None = None


@dataclass(frozen=True)
class PurchasePlan:
    reference: str
    title: str
    traffic_gb: int
    duration_days: int
    device_limit: int
    location_code: str
    location_label: str
    quality_code: str
    price_toman: int


@dataclass(frozen=True)
class PurchaseResult:
    order_reference: str
    status: str
    fulfillment_status: str
    plan: PurchasePlan
    service_reference: str | None = None
    expires_at: datetime | None = None
    refunded: bool = False


@dataclass(frozen=True)
class SessionSummary:
    ref: str
    label: str
    last_seen_at: datetime
    current: bool = False


@dataclass(frozen=True)
class Ticket:
    ref: str
    owner_ref: str
    category: str
    subject: str
    message: str
    status: str = "open"


@dataclass
class ConversationState:
    owner_ref: str
    kind: ConversationKind
    started_at: datetime
    expires_at: datetime
    data: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    nonce: str = ""

    def expired(self, at: datetime) -> bool:
        return at >= self.expires_at


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}

    def start(self, key: str, state: ConversationState) -> None:
        self._states[key] = state

    def get(self, key: str, at: datetime) -> ConversationState | None:
        state = self._states.get(key)
        if state and state.expired(at):
            self._states.pop(key, None)
            return None
        return state

    def cancel(self, key: str) -> bool:
        return self._states.pop(key, None) is not None


class CustomerPortalPort(Protocol):
    def purchase_catalog(self, context: CustomerContext) -> list[PurchasePlan]: ...
    def purchase_plan(self, context: CustomerContext, reference: str) -> PurchasePlan | None: ...
    def confirm_purchase(
        self, context: CustomerContext, reference: str, idempotency_key: str
    ) -> PurchaseResult: ...
    def purchase_order(self, context: CustomerContext, reference: str) -> PurchaseResult | None: ...
    def profile(self, context: CustomerContext) -> CustomerProfile: ...
    def services(self, context: CustomerContext) -> list[ServiceSummary]: ...
    def service(self, context: CustomerContext, service_ref: str) -> ServiceSummary | None: ...
    def wallet_balance(self, context: CustomerContext) -> tuple[int, str]: ...
    def transactions(self, context: CustomerContext) -> list[WalletTransaction]: ...
    def sessions(self, context: CustomerContext) -> list[SessionSummary]: ...
    def revoke_session(self, context: CustomerContext, session_ref: str) -> bool: ...
    def create_ticket(
        self, context: CustomerContext, category: str, subject: str, message: str
    ) -> Ticket: ...
    def tickets(self, context: CustomerContext) -> list[Ticket]: ...
    def notification_preferences(self, context: CustomerContext) -> NotificationPreferences: ...
    def update_notification_preference(
        self, context: CustomerContext, key: str, enabled: bool, idempotency_key: str
    ) -> NotificationPreferences: ...
    def create_manual_topup(
        self, context: CustomerContext, amount_rial: int, idempotency_key: str
    ) -> ManualTopup: ...
    def manual_topups(self, context: CustomerContext) -> list[ManualTopup]: ...
    def manual_topup(self, context: CustomerContext, reference: str) -> ManualTopup | None: ...
    def cancel_manual_topup(
        self, context: CustomerContext, reference: str, idempotency_key: str
    ) -> ManualTopup: ...
    def manual_topup_destination_mode(self, context: CustomerContext, reference: str) -> str: ...
    def upload_manual_topup_receipt(
        self,
        context: CustomerContext,
        reference: str,
        content: bytes,
        content_type: str,
        idempotency_key: str,
    ) -> ManualTopup: ...


class InMemoryCustomerPortal(CustomerPortalPort):
    def __init__(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        self.created_tickets: dict[tuple[str, str, str], Ticket] = {}
        self._services = [
            ServiceSummary(
                "svc-a",
                "user-42",
                "پلن استاندارد",
                "active",
                now + timedelta(days=10),
                80,
                100,
                "Germany",
                True,
            ),
            ServiceSummary(
                "svc-b",
                "user-42",
                "پلن آزمایشی",
                "expired",
                now - timedelta(days=2),
                0,
                50,
                "Netherlands",
                False,
            ),
        ]
        self._transactions = [
            WalletTransaction(
                f"tx-{i}", 10000 * i, "IRR", "posted", "credit", now - timedelta(days=i)
            )
            for i in range(1, 13)
        ]
        self._sessions = [
            SessionSummary("sess-current", "Telegram bot", now, True),
            SessionSummary("sess-web", "Customer web", now - timedelta(days=1)),
        ]
        self._languages: dict[str, str] = {}
        self._notification_preferences: dict[str, NotificationPreferences] = {}
        self._notification_idempotency: dict[tuple[str, str], NotificationPreferences] = {}
        self._manual_topups: dict[str, ManualTopup] = {}
        self._manual_topup_cancellations: dict[str, ManualTopup] = {}
        self._purchase_plans = [
            PurchasePlan("basic", "پلن استاندارد", 50, 30, 1, "de", "آلمان", "standard", 120_000)
        ]
        self._purchases: dict[str, PurchaseResult] = {}

    def purchase_catalog(self, context: CustomerContext) -> list[PurchasePlan]:
        return list(self._purchase_plans)

    def purchase_plan(self, context: CustomerContext, reference: str) -> PurchasePlan | None:
        return next((plan for plan in self._purchase_plans if plan.reference == reference), None)

    def confirm_purchase(
        self, context: CustomerContext, reference: str, idempotency_key: str
    ) -> PurchaseResult:
        if idempotency_key in self._purchases:
            return self._purchases[idempotency_key]
        plan = self.purchase_plan(context, reference)
        if plan is None:
            raise ValueError("plan unavailable")
        result = PurchaseResult(f"ord_{idempotency_key[-8:]}", "ACCEPTED", "PROVISIONING", plan)
        self._purchases[idempotency_key] = result
        return result

    def purchase_order(self, context: CustomerContext, reference: str) -> PurchaseResult | None:
        return next(
            (item for item in self._purchases.values() if item.order_reference == reference), None
        )

    def profile(self, context: CustomerContext) -> CustomerProfile:
        return CustomerProfile(
            "مشتری",
            True,
            AccountStatus.ACTIVE,
            datetime(2026, 1, 1, tzinfo=UTC),
            "fa",
        )

    def services(self, context: CustomerContext) -> list[ServiceSummary]:
        return [s for s in self._services if s.owner_ref == context.customer_ref]

    def service(self, context: CustomerContext, service_ref: str) -> ServiceSummary | None:
        return next((s for s in self.services(context) if s.ref == service_ref), None)

    def wallet_balance(self, context: CustomerContext) -> tuple[int, str]:
        return (250000, "IRR")

    def transactions(self, context: CustomerContext) -> list[WalletTransaction]:
        return list(self._transactions)

    def create_manual_topup(
        self, context: CustomerContext, amount_rial: int, idempotency_key: str
    ) -> ManualTopup:
        reference = f"mtp_{idempotency_key.encode().hex()[:12]}"
        if reference not in self._manual_topups:
            self._manual_topups[reference] = ManualTopup(
                reference, amount_rial // 10, "AWAITING_SUPPORT", datetime.now(UTC)
            )
        return self._manual_topups[reference]

    def manual_topups(self, context: CustomerContext) -> list[ManualTopup]:
        return list(self._manual_topups.values())

    def manual_topup(self, context: CustomerContext, reference: str) -> ManualTopup | None:
        return self._manual_topups.get(reference)

    def cancel_manual_topup(
        self, context: CustomerContext, reference: str, idempotency_key: str
    ) -> ManualTopup:
        if idempotency_key in self._manual_topup_cancellations:
            return self._manual_topup_cancellations[idempotency_key]
        request = self._manual_topups[reference]
        if request.status not in {"AWAITING_SUPPORT", "AWAITING_RECEIPT", "NEEDS_RESUBMISSION"}:
            raise ValueError("manual top-up cannot be cancelled")
        cancelled = ManualTopup(
            request.reference,
            request.amount_toman,
            "CANCELLED",
            request.created_at,
            request.submitted_at,
            request.verified_amount_toman,
            request.bonus_amount_toman,
            request.total_credited_toman,
        )
        self._manual_topups[reference] = cancelled
        self._manual_topup_cancellations[idempotency_key] = cancelled
        return cancelled

    def manual_topup_destination_mode(self, context: CustomerContext, reference: str) -> str:
        return "SUPPORT_ONLY"

    def upload_manual_topup_receipt(
        self,
        context: CustomerContext,
        reference: str,
        content: bytes,
        content_type: str,
        idempotency_key: str,
    ) -> ManualTopup:
        request = self._manual_topups[reference]
        updated = ManualTopup(
            reference, request.amount_toman, "UNDER_REVIEW", request.created_at, datetime.now(UTC)
        )
        self._manual_topups[reference] = updated
        return updated

    def sessions(self, context: CustomerContext) -> list[SessionSummary]:
        return list(self._sessions)

    def revoke_session(self, context: CustomerContext, session_ref: str) -> bool:
        before = len(self._sessions)
        self._sessions = [s for s in self._sessions if s.ref != session_ref or s.current]
        return len(self._sessions) != before

    def create_ticket(
        self, context: CustomerContext, category: str, subject: str, message: str
    ) -> Ticket:
        key = (context.customer_ref, subject, message)
        if key not in self.created_tickets:
            ref = f"tic-{len(self.created_tickets) + 1}"
            self.created_tickets[key] = Ticket(
                ref, context.customer_ref, category, subject, message
            )
        return self.created_tickets[key]

    def tickets(self, context: CustomerContext) -> list[Ticket]:
        return [t for t in self.created_tickets.values() if t.owner_ref == context.customer_ref]

    def notification_preferences(self, context: CustomerContext) -> NotificationPreferences:
        prefs = self._notification_preferences.get(context.customer_ref)
        if prefs is None:
            prefs = NotificationPreferences()
            self._notification_preferences[context.customer_ref] = prefs
        return prefs

    def update_notification_preference(
        self, context: CustomerContext, key: str, enabled: bool, idempotency_key: str
    ) -> NotificationPreferences:
        idem = (context.customer_ref, idempotency_key)
        if idem in self._notification_idempotency:
            return self._notification_idempotency[idem]
        current = self.notification_preferences(context)
        values = {
            "service_expiry_enabled": current.service_expiry_enabled,
            "low_traffic_enabled": current.low_traffic_enabled,
            "payment_enabled": current.payment_enabled,
            "support_reply_enabled": current.support_reply_enabled,
            "announcements_enabled": current.announcements_enabled,
        }
        if key not in values:
            raise ValueError("unknown notification preference")
        values[key] = enabled
        updated = NotificationPreferences(**values)
        self._notification_preferences[context.customer_ref] = updated
        self._notification_idempotency[idem] = updated
        return updated


def page_items[TItem](items: list[TItem], page: int, per_page: int = 5) -> tuple[list[TItem], bool]:
    start = max(page, 0) * per_page
    chunk = list(islice(items, start, start + per_page + 1))
    return chunk[:per_page], len(chunk) > per_page
