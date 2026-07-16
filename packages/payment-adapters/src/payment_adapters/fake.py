from .contracts import PaymentHealth


class FakePaymentProvider:
    async def health_check(self) -> PaymentHealth:
        return PaymentHealth(healthy=True)

    async def create_payment(self, amount_minor: int, currency: str, idempotency_key: str) -> str:
        return f"fake-payment-{idempotency_key}-{amount_minor}-{currency}"
