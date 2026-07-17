from __future__ import annotations

import hashlib
import threading
import time


class IdempotencyUnavailable(RuntimeError):
    pass


class InMemoryUpdateIdempotency:
    def __init__(self) -> None:
        self._claims: dict[str, float] = {}
        self._lock = threading.Lock()

    def claim(self, update_id: int, ttl_seconds: int) -> bool:
        key = hashlib.sha256(f"tg-update:{update_id}".encode()).hexdigest()
        now = time.time()
        with self._lock:
            self._claims = {k: exp for k, exp in self._claims.items() if exp > now}
            if key in self._claims:
                return False
            self._claims[key] = now + ttl_seconds
            return True
