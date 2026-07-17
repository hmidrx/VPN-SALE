from __future__ import annotations

from dataclasses import dataclass

from .contracts import AdapterEnvironment, PaymentGatewayAdapter


class AdapterRegistryError(ValueError):
    pass


@dataclass
class PaymentAdapterRegistry:
    environment: AdapterEnvironment
    _adapters: dict[tuple[str, str], PaymentGatewayAdapter] | None = None

    def _store(self) -> dict[tuple[str, str], PaymentGatewayAdapter]:
        if self._adapters is None:
            self._adapters = {}
        return self._adapters

    def register(self, adapter: PaymentGatewayAdapter) -> None:
        capabilities = adapter.capabilities()
        if (
            capabilities.provider_code == "fake"
            and self.environment == AdapterEnvironment.PRODUCTION
        ):
            raise AdapterRegistryError("fake payment adapter is rejected in production")
        key = (capabilities.provider_code, capabilities.adapter_version)
        adapters = self._store()
        if key in adapters:
            raise AdapterRegistryError("payment adapter version already registered")
        adapters[key] = adapter

    def get(self, provider_code: str, adapter_version: str) -> PaymentGatewayAdapter:
        try:
            return self._store()[(provider_code, adapter_version)]
        except KeyError as exc:
            raise AdapterRegistryError("unknown payment adapter version") from exc
