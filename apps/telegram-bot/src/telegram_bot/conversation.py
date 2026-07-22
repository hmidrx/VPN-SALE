from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from telegram_bot.screens import ScreenId

MAX_STACK = 8
STATE_TTL_SECONDS = 60 * 60 * 24


@dataclass(frozen=True)
class ConversationStateV2:
    current_screen: ScreenId = ScreenId.HOME
    navigation_stack: tuple[ScreenId, ...] = ()
    language_selection_active: bool = False
    active_menu_message_id: int | None = None
    state_version: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(seconds=STATE_TTL_SECONDS)
    )

    def expired(self, at: datetime) -> bool:
        return at >= self.expires_at

    def move_to(self, screen: ScreenId, *, push: bool = True) -> ConversationStateV2:
        stack = self.navigation_stack
        if push and screen != self.current_screen:
            stack = (*stack, self.current_screen)[-MAX_STACK:]
        now = datetime.now(UTC)
        return replace(
            self,
            current_screen=screen,
            navigation_stack=stack,
            language_selection_active=screen == ScreenId.LANGUAGE,
            state_version=self.state_version + 1,
            updated_at=now,
            expires_at=now + timedelta(seconds=STATE_TTL_SECONDS),
        )

    def back(self) -> ConversationStateV2:
        if not self.navigation_stack:
            return self.move_to(ScreenId.HOME, push=False)
        now = datetime.now(UTC)
        return replace(
            self,
            current_screen=self.navigation_stack[-1],
            navigation_stack=self.navigation_stack[:-1],
            language_selection_active=False,
            state_version=self.state_version + 1,
            updated_at=now,
            expires_at=now + timedelta(seconds=STATE_TTL_SECONDS),
        )


class ConversationStoreV2(Protocol):
    def get(self, key: str, at: datetime) -> ConversationStateV2: ...
    def save(self, key: str, state: ConversationStateV2) -> None: ...
    def cancel(self, key: str) -> bool: ...


class DurableMemoryConversationStore(ConversationStoreV2):
    def __init__(self) -> None:
        self._states: dict[str, ConversationStateV2] = {}

    def get(self, key: str, at: datetime) -> ConversationStateV2:
        state = self._states.get(key)
        if state is None or state.expired(at):
            fresh = ConversationStateV2()
            self._states[key] = fresh
            return fresh
        return state

    def save(self, key: str, state: ConversationStateV2) -> None:
        self._states[key] = state

    def cancel(self, key: str) -> bool:
        return self._states.pop(key, None) is not None
