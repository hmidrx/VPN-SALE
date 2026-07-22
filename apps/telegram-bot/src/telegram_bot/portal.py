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
class CustomerProfile:
    display_name: str
    telegram_linked: bool
    account_state: AccountStatus
    created_at: datetime
    language: str


@dataclass(frozen=True)
class ServiceSummary:
    ref: str
    owner_ref: str
    plan_name: str
    status: str
    expires_at: datetime | None
    remaining_gb: int
    total_gb: int
    location: str
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
    def profile(self, context: CustomerContext) -> CustomerProfile: ...
    def set_language(self, context: CustomerContext, locale: str) -> None: ...
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

    def profile(self, context: CustomerContext) -> CustomerProfile:
        return CustomerProfile(
            "مشتری",
            True,
            AccountStatus.ACTIVE,
            datetime(2026, 1, 1, tzinfo=UTC),
            self._languages.get(context.customer_ref, context.locale),
        )

    def set_language(self, context: CustomerContext, locale: str) -> None:
        self._languages[context.customer_ref] = locale

    def services(self, context: CustomerContext) -> list[ServiceSummary]:
        return [s for s in self._services if s.owner_ref == context.customer_ref]

    def service(self, context: CustomerContext, service_ref: str) -> ServiceSummary | None:
        return next((s for s in self.services(context) if s.ref == service_ref), None)

    def wallet_balance(self, context: CustomerContext) -> tuple[int, str]:
        return (250000, "IRR")

    def transactions(self, context: CustomerContext) -> list[WalletTransaction]:
        return list(self._transactions)

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


def page_items[TItem](items: list[TItem], page: int, per_page: int = 5) -> tuple[list[TItem], bool]:
    start = max(page, 0) * per_page
    chunk = list(islice(items, start, start + per_page + 1))
    return chunk[:per_page], len(chunk) > per_page
