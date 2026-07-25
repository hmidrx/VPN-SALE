from __future__ import annotations

import hashlib
import hmac
import threading
import time


class RateLimitExceeded(RuntimeError):
    pass


class RateLimitUnavailable(RuntimeError):
    pass


class InMemoryBotRateLimiter:
    def __init__(self, secret: str) -> None:
        self.secret = secret.encode()
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def key_for(self, scope: str, telegram_user_id: int) -> str:
        digest = hmac.new(self.secret, str(telegram_user_id).encode(), hashlib.sha256).hexdigest()
        return f"bot-rl:{scope}:{digest}"

    def check(self, scope: str, telegram_user_id: int, limit: int, window_seconds: int) -> None:
        key = self.key_for(scope, telegram_user_id)
        now = time.time()
        with self._lock:
            hits = [ts for ts in self._hits.get(key, []) if now - ts < window_seconds]
            if len(hits) >= limit:
                raise RateLimitExceeded
            hits.append(now)
            self._hits[key] = hits


class InFlightCallbackDeduplicator:
    """Process-local guard; durable update-id claims remain the cross-process defense."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def _key(self, telegram_user_id: int, callback_data: str) -> str:
        material = f"{telegram_user_id}:{callback_data}".encode()
        return hmac.new(self._secret, material, hashlib.sha256).hexdigest()

    def claim(self, telegram_user_id: int, callback_data: str) -> str | None:
        key = self._key(telegram_user_id, callback_data)
        with self._lock:
            if key in self._active:
                return None
            self._active.add(key)
        return key

    def release(self, key: str) -> None:
        with self._lock:
            self._active.discard(key)
