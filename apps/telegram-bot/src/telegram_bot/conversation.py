from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from urllib.parse import unquote, urlparse

from redis import Redis

from telegram_bot.screens import ScreenId

MAX_STACK = 8
STATE_TTL_SECONDS = 60 * 60 * 24


@dataclass(frozen=True)
class ConversationStateV2:
    current_screen: ScreenId = ScreenId.HOME
    navigation_stack: tuple[ScreenId, ...] = ()
    active_menu_message_id: int | None = None
    state_version: int = 1
    conversation_kind: str | None = None
    expected_input: str | None = None
    amount_toman: int | None = None
    idempotency_key: str | None = None
    active_manual_topup_reference: str | None = None
    selected_plan_reference: str | None = None
    selected_options: str | None = None
    active_order_reference: str | None = None
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
            state_version=self.state_version + 1,
            updated_at=now,
            expires_at=now + timedelta(seconds=STATE_TTL_SECONDS),
        )

    def start_topup(self, idempotency_key: str) -> ConversationStateV2:
        now = datetime.now(UTC)
        return replace(
            self,
            conversation_kind="manual_topup",
            expected_input="amount",
            amount_toman=None,
            idempotency_key=idempotency_key,
            state_version=self.state_version + 1,
            updated_at=now,
            expires_at=now + timedelta(seconds=STATE_TTL_SECONDS),
        )

    def review_topup(self, amount_toman: int) -> ConversationStateV2:
        return replace(self, expected_input="confirmation", amount_toman=amount_toman)

    def start_purchase(
        self, plan_reference: str, options: str, idempotency_key: str
    ) -> ConversationStateV2:
        now = datetime.now(UTC)
        return replace(
            self,
            conversation_kind="purchase",
            expected_input="purchase_confirmation",
            selected_plan_reference=plan_reference,
            selected_options=options,
            idempotency_key=idempotency_key,
            active_order_reference=None,
            state_version=self.state_version + 1,
            updated_at=now,
            expires_at=now + timedelta(seconds=STATE_TTL_SECONDS),
        )


class ConversationStoreV2(Protocol):
    def get(self, key: str, at: datetime) -> ConversationStateV2: ...
    def save(self, key: str, state: ConversationStateV2) -> None: ...
    def cancel(self, key: str) -> bool: ...


class SyncRedis(Protocol):
    def get(self, name: str) -> object | None: ...
    def set(self, name: str, value: str, *, ex: int) -> object: ...
    def delete(self, *names: str) -> int: ...


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


class RedisConversationStore(ConversationStoreV2):
    """TTL-bound state; keys are HMAC-derived by the handler and values contain no PII."""

    def __init__(self, redis_url: str, *, client: SyncRedis | None = None) -> None:
        parsed = urlparse(redis_url)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            raise ValueError("invalid Redis URL")
        database = int(parsed.path.removeprefix("/") or "0")
        self._redis = client or cast(
            SyncRedis,
            Redis(
                host=parsed.hostname,
                port=parsed.port or 6379,
                db=database,
                username=unquote(parsed.username) if parsed.username else None,
                password=unquote(parsed.password) if parsed.password else None,
                ssl=parsed.scheme == "rediss",
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            ),
        )

    def get(self, key: str, at: datetime) -> ConversationStateV2:
        raw = self._redis.get(key)
        if raw is None:
            return ConversationStateV2()
        if not isinstance(raw, str):
            self._redis.delete(key)
            return ConversationStateV2()
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                raise ValueError("conversation state must be an object")
            value = cast(dict[str, object], decoded)
            stack_value = value["stack"]
            if not isinstance(stack_value, list):
                raise ValueError("conversation stack must be a list")
            stack_items = cast(list[object], stack_value)
            stack = tuple(ScreenId(str(item)) for item in stack_items[-MAX_STACK:])
            menu_message = value.get("menu_message")
            state = ConversationStateV2(
                current_screen=ScreenId(str(value["screen"])),
                navigation_stack=stack,
                active_menu_message_id=(menu_message if isinstance(menu_message, int) else None),
                state_version=int(str(value["version"])),
                conversation_kind=(
                    str(value["conversation_kind"]) if value.get("conversation_kind") else None
                ),
                expected_input=(
                    str(value["expected_input"]) if value.get("expected_input") else None
                ),
                amount_toman=(
                    int(str(value["amount_toman"]))
                    if value.get("amount_toman") is not None
                    else None
                ),
                idempotency_key=(
                    str(value["idempotency_key"]) if value.get("idempotency_key") else None
                ),
                active_manual_topup_reference=(
                    str(value["active_manual_topup_reference"])
                    if value.get("active_manual_topup_reference")
                    else None
                ),
                selected_plan_reference=(
                    str(value["selected_plan_reference"])
                    if value.get("selected_plan_reference")
                    else None
                ),
                selected_options=(
                    str(value["selected_options"]) if value.get("selected_options") else None
                ),
                active_order_reference=(
                    str(value["active_order_reference"])
                    if value.get("active_order_reference")
                    else None
                ),
                updated_at=datetime.fromisoformat(str(value["updated_at"])),
                expires_at=datetime.fromisoformat(str(value["expires_at"])),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._redis.delete(key)
            return ConversationStateV2()
        if state.expired(at):
            self._redis.delete(key)
            return ConversationStateV2()
        return state

    def save(self, key: str, state: ConversationStateV2) -> None:
        payload = json.dumps(
            {
                "screen": state.current_screen.value,
                "stack": [item.value for item in state.navigation_stack[-MAX_STACK:]],
                "menu_message": state.active_menu_message_id,
                "version": state.state_version,
                "conversation_kind": state.conversation_kind,
                "expected_input": state.expected_input,
                "amount_toman": state.amount_toman,
                "idempotency_key": state.idempotency_key,
                "active_manual_topup_reference": state.active_manual_topup_reference,
                "selected_plan_reference": state.selected_plan_reference,
                "selected_options": state.selected_options,
                "active_order_reference": state.active_order_reference,
                "updated_at": state.updated_at.isoformat(),
                "expires_at": state.expires_at.isoformat(),
            }
        )
        self._redis.set(key, payload, ex=STATE_TTL_SECONDS)

    def cancel(self, key: str) -> bool:
        return bool(self._redis.delete(key))
