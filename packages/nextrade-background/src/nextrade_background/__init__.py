"""Android foreground execution, started explicitly from the visible app."""
import flet as ft


@ft.control("NexTradeBackground")
class NexTradeBackground(ft.Service):
    async def start(self) -> bool:
        return await self._invoke_method("start", timeout=120) is True

    async def stop(self) -> None:
        await self._invoke_method("stop")

    async def is_enabled(self) -> bool:
        return await self._invoke_method("is_enabled") is True
