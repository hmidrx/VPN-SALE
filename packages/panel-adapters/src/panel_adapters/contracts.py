from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PanelHealth:
    healthy: bool
    latency_ms: int | None = None
    version: str | None = None


class PanelProvider(Protocol):
    async def health_check(self) -> PanelHealth: ...
    async def capabilities(self) -> set[str]: ...
