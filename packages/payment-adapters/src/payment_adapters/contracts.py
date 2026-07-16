from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PaymentHealth:
    healthy: bool


class PaymentProvider(Protocol):
    async def health_check(self) -> PaymentHealth: ...

    async def create_payment(
        self,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
    ) -> str: ...
