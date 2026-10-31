"""Plugin lifecycle; incoming messages are dispatched by AstrBot core."""

from astrbot.api.star import Star

from .custom_waiter import SessionWaiter


class Waiter(Star):
    async def terminate(self) -> None:
        await SessionWaiter.cancel_all()
