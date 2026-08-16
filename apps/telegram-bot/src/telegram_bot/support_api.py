"""Production Telegram support adapter over the private platform bridge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from telegram_bot.account_security_api import AccountSecurityPrivatePlatformClient
from telegram_bot.internal_api import (
    AuthoritativePrivateApiError,
    PrivateApiUnavailable,
)
from telegram_bot.portal import CustomerContext

_TICKET_REFERENCE = re.compile(r"^SUP-[0-9a-f]{24}$")


class SupportOutcomeUnknown(PrivateApiUnavailable):
    """An idempotent support mutation may have committed and needs safe reconciliation."""


@dataclass(frozen=True)
class SupportTicketMessage:
    sequence: int
    sender_type: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class SupportTicket:
    reference: str
    subject: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: tuple[SupportTicketMessage, ...] = ()


class NativeSupportPortal(Protocol):
    def support_tickets(self, context: CustomerContext) -> list[SupportTicket]: ...
    def support_ticket(self, context: CustomerContext, reference: str) -> SupportTicket | None: ...
    def create_support_ticket(
        self,
        context: CustomerContext,
        subject: str,
        message: str,
        idempotency_key: str,
    ) -> SupportTicket: ...
    def reply_support_ticket(
        self,
        context: CustomerContext,
        reference: str,
        message: str,
        idempotency_key: str,
    ) -> SupportTicket: ...


class SupportPrivatePlatformClient(AccountSecurityPrivatePlatformClient, NativeSupportPortal):
    @staticmethod
    def _ticket(data: dict[str, Any]) -> SupportTicket:
        reference = data.get("reference")
        subject = data.get("subject")
        status = data.get("status")
        created_at = data.get("created_at")
        updated_at = data.get("updated_at")
        if (
            not isinstance(reference, str)
            or _TICKET_REFERENCE.fullmatch(reference) is None
            or not isinstance(subject, str)
            or not subject
            or len(subject) > 160
            or not isinstance(status, str)
            or not isinstance(created_at, str)
            or not isinstance(updated_at, str)
        ):
            raise PrivateApiUnavailable("اطلاعات تیکت پشتیبانی قابل استفاده نیست.")
        try:
            created = datetime.fromisoformat(created_at)
            updated = datetime.fromisoformat(updated_at)
        except ValueError as exc:
            raise PrivateApiUnavailable("اطلاعات تیکت پشتیبانی قابل استفاده نیست.") from exc
        raw_messages = data.get("messages", [])
        if not isinstance(raw_messages, list) or len(raw_messages) > 100:
            raise PrivateApiUnavailable("اطلاعات تیکت پشتیبانی قابل استفاده نیست.")
        messages: list[SupportTicketMessage] = []
        for item in cast(list[object], raw_messages):
            if not isinstance(item, dict):
                raise PrivateApiUnavailable("اطلاعات تیکت پشتیبانی قابل استفاده نیست.")
            values = cast(dict[str, Any], item)
            body = values.get("body")
            sender = values.get("sender_type")
            sequence = values.get("sequence")
            timestamp = values.get("created_at")
            if (
                not isinstance(body, str)
                or len(body) > 4000
                or not isinstance(sender, str)
                or not isinstance(sequence, int)
                or not isinstance(timestamp, str)
            ):
                raise PrivateApiUnavailable("اطلاعات پیام پشتیبانی قابل استفاده نیست.")
            try:
                created_message = datetime.fromisoformat(timestamp)
            except ValueError as exc:
                raise PrivateApiUnavailable("اطلاعات پیام پشتیبانی قابل استفاده نیست.") from exc
            messages.append(SupportTicketMessage(sequence, sender, body, created_message))
        return SupportTicket(reference, subject, status, created, updated, tuple(messages))

    def support_tickets(self, context: CustomerContext) -> list[SupportTicket]:
        data = self._request("GET", "/support/tickets", context.telegram_user_id)
        raw_items = data.get("items")
        if not isinstance(raw_items, list) or len(raw_items) > 20:
            raise PrivateApiUnavailable("فهرست تیکت‌ها قابل استفاده نیست.")
        tickets: list[SupportTicket] = []
        for item in cast(list[object], raw_items):
            if not isinstance(item, dict):
                raise PrivateApiUnavailable("فهرست تیکت‌ها قابل استفاده نیست.")
            tickets.append(self._ticket(cast(dict[str, Any], item)))
        return tickets

    def support_ticket(self, context: CustomerContext, reference: str) -> SupportTicket | None:
        if _TICKET_REFERENCE.fullmatch(reference) is None:
            return None
        try:
            data = self._request(
                "GET", f"/support/tickets/{reference}", context.telegram_user_id
            )
        except AuthoritativePrivateApiError as exc:
            if exc.status_code == 404:
                return None
            raise
        return self._ticket(data)

    def _support_mutation(
        self,
        method: str,
        path: str,
        telegram_id: int,
        body: dict[str, str],
        idempotency_key: str,
    ) -> SupportTicket:
        try:
            data = self._request(method, path, telegram_id, body, idempotency_key)
        except AuthoritativePrivateApiError:
            raise
        except PrivateApiUnavailable:
            # The backend mutation is idempotent. Replay once with exactly the same key/body;
            # if transport is still ambiguous, the caller must reconcile through a GET.
            try:
                data = self._request(method, path, telegram_id, body, idempotency_key)
            except AuthoritativePrivateApiError:
                raise
            except PrivateApiUnavailable as exc:
                raise SupportOutcomeUnknown("نتیجه عملیات پشتیبانی هنوز مشخص نیست.") from exc
        return self._ticket(data)

    def create_support_ticket(
        self,
        context: CustomerContext,
        subject: str,
        message: str,
        idempotency_key: str,
    ) -> SupportTicket:
        return self._support_mutation(
            "POST",
            "/support/tickets",
            context.telegram_user_id,
            {"subject": subject, "message": message},
            idempotency_key,
        )

    def reply_support_ticket(
        self,
        context: CustomerContext,
        reference: str,
        message: str,
        idempotency_key: str,
    ) -> SupportTicket:
        if _TICKET_REFERENCE.fullmatch(reference) is None:
            raise PrivateApiUnavailable("تیکت معتبر نیست.")
        return self._support_mutation(
            "POST",
            f"/support/tickets/{reference}/reply",
            context.telegram_user_id,
            {"message": message},
            idempotency_key,
        )
