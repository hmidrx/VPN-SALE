from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from telegram_bot.conversation import (
    MAX_SUPPORT_CURSOR_LENGTH,
    MAX_SUPPORT_PAGE_STACK,
    ConversationStateV2,
    RedisConversationStore,
)
from telegram_bot.screens import ScreenId


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str, *, ex: int) -> object:
        self.values[name] = value
        self.ttls[name] = ex
        return True

    def delete(self, *names: str) -> int:
        removed = sum(name in self.values for name in names)
        for name in names:
            self.values.pop(name, None)
        return removed


def store(client: FakeRedis) -> RedisConversationStore:
    return RedisConversationStore("redis://unused", client=client)


def test_missing_key_returns_fresh_state() -> None:
    assert store(FakeRedis()).get("missing", datetime.now(UTC)).current_screen is ScreenId.HOME


def test_valid_state_round_trip_save_and_cancel() -> None:
    client = FakeRedis()
    subject = store(client)
    state = ConversationStateV2().move_to(ScreenId.WALLET)
    subject.save("owner", state)
    assert subject.get("owner", datetime.now(UTC)).current_screen is ScreenId.WALLET
    assert client.ttls["owner"] == 86_400
    assert subject.cancel("owner")


def test_support_pagination_state_is_bounded_and_contains_no_message_body() -> None:
    client = FakeRedis()
    subject = store(client)
    cursors = tuple(f"cursor-{index}" for index in range(MAX_SUPPORT_PAGE_STACK + 4))
    state = ConversationStateV2(
        support_ticket_cursor="ticket-current",
        support_ticket_next_cursor="ticket-next",
        support_ticket_previous_cursors=cursors,
        active_support_reference="SUP-aaaaaaaaaaaaaaaaaaaaaaaa",
        support_message_cursor="message-current",
        support_message_next_cursor="message-next",
        support_message_previous_cursors=cursors,
    )
    subject.save("owner", state)
    raw = client.values["owner"]
    assert "customer secret message" not in raw
    loaded = subject.get("owner", datetime.now(UTC))
    assert loaded.support_ticket_cursor == "ticket-current"
    assert loaded.support_message_next_cursor == "message-next"
    assert len(loaded.support_ticket_previous_cursors) == MAX_SUPPORT_PAGE_STACK
    assert len(loaded.support_message_previous_cursors) == MAX_SUPPORT_PAGE_STACK
    assert loaded.support_ticket_previous_cursors[0] == "cursor-4"


def test_overlong_support_cursor_is_discarded_on_read() -> None:
    client = FakeRedis()
    subject = store(client)
    subject.save(
        "owner",
        ConversationStateV2(
            support_ticket_cursor="x" * (MAX_SUPPORT_CURSOR_LENGTH + 1),
            support_message_next_cursor="y" * (MAX_SUPPORT_CURSOR_LENGTH + 1),
        ),
    )
    loaded = subject.get("owner", datetime.now(UTC))
    assert loaded.support_ticket_cursor is None
    assert loaded.support_message_next_cursor is None


@pytest.mark.parametrize("payload", ["not-json", "[]", '{"screen":"missing"}'])
def test_malformed_or_unexpected_state_is_removed(payload: str) -> None:
    client = FakeRedis()
    client.values["owner"] = payload
    assert store(client).get("owner", datetime.now(UTC)).current_screen is ScreenId.HOME
    assert "owner" not in client.values


def test_expired_state_is_removed() -> None:
    client = FakeRedis()
    subject = store(client)
    past = datetime.now(UTC) - timedelta(days=2)
    subject.save(
        "owner",
        ConversationStateV2(updated_at=past, expires_at=past + timedelta(seconds=1)),
    )
    assert subject.get("owner", datetime.now(UTC)).current_screen is ScreenId.HOME
    assert "owner" not in client.values


def test_redis_unavailable_fails_closed() -> None:
    class UnavailableRedis(FakeRedis):
        def get(self, name: str) -> str | None:
            raise ConnectionError("unavailable")

    with pytest.raises(ConnectionError, match="unavailable"):
        store(UnavailableRedis()).get("owner", datetime.now(UTC))
