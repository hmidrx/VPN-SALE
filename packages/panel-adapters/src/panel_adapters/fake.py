from .contracts import PanelHealth


class FakePanelProvider:
    async def health_check(self) -> PanelHealth:
        return PanelHealth(healthy=True, latency_ms=1, version="fake")

    async def capabilities(self) -> set[str]:
        return {"create_subscription", "reconcile"}
