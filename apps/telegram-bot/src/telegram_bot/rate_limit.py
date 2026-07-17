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
