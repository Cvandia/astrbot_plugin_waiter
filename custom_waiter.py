"""One-shot waiters backed by AstrBot's native session dispatcher."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import math
import warnings
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from astrbot.api.event import AstrMessageEvent
from astrbot.core.utils import session_waiter as native

USER_SESSIONS: dict[str, SessionWaiter] = {}


def get_session_id(event: AstrMessageEvent) -> str:
    """Isolate a sender within one platform instance and conversation."""
    return "waiter:" + json.dumps(
        [event.unified_msg_origin, str(event.get_sender_id())],
        ensure_ascii=False,
        separators=(",", ":"),
    )


class SessionAlreadyWaitingError(RuntimeError):
    """A waiter already owns this session; it must not be overwritten."""


class _SessionFilter(native.SessionFilter):
    def __init__(self, scoped: bool):
        self.scoped = scoped

    def filter(self, event: AstrMessageEvent) -> str:
        if self.scoped:
            return get_session_id(event)
        # Historical routing used only the sender ID. Keep it for migration.
        return f"hoyocos_{event.get_sender_id()}"


class SessionWaiter:
    """Wait for one input and return the handler's result.

    Prefer ``SessionWaiter.from_event(event)``. Explicit string IDs remain
    supported for manual ``trigger`` calls; ``hoyocos_<sender>`` also retains
    its historical (cross-conversation) routing.
    """

    def __init__(self, session_id: str, *, receive_event: bool = False):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id 必须是非空字符串")
        if session_id.startswith("hoyocos_"):
            warnings.warn(
                "hoyocos_<sender> 不隔离平台或群聊，请改用 SessionWaiter.from_event(event)",
                DeprecationWarning,
                stacklevel=2,
            )
        self.session_id = session_id
        self.receive_event = receive_event
        self.future: asyncio.Future | None = None
        self.handler: Callable | None = None
        self._native: native.SessionWaiter | None = None
        self._processing: asyncio.Task | None = None
        self._closed: asyncio.Event | None = None
        self._claimed = False
        self._active = False
        self._result: Any = None

    @classmethod
    def from_event(
        cls, event: AstrMessageEvent, *, receive_event: bool = False
    ) -> SessionWaiter:
        return cls(get_session_id(event), receive_event=receive_event)

    async def register_wait(self, handler: Callable, timeout: float = 30) -> Any:
        """Register before yielding control; timeout includes callback execution."""
        if not callable(handler):
            raise TypeError("handler 必须可调用")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout 必须为正数秒数")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必须为有限正数")
        if (
            self._active
            or self.session_id in USER_SESSIONS
            or self.session_id in native.USER_SESSIONS
        ):
            raise SessionAlreadyWaitingError("该会话已有等待器")

        session_filter = _SessionFilter(self.session_id.startswith("waiter:"))
        waiter = native.SessionWaiter(session_filter, self.session_id, False)
        self._native = waiter
        self.future = waiter.session_controller.future
        self.handler = handler
        self._claimed = False
        self._active = True
        self._result = None
        self._closed = asyncio.Event()
        USER_SESSIONS[self.session_id] = self
        native.FILTERS.append(session_filter)

        async def on_input(controller, event: AstrMessageEvent):
            await self._deliver(event if self.receive_event else event.message_str)

        try:
            await waiter.register_wait(on_input, timeout)
            return self._result
        finally:
            # Native dispatch owns its registry and filter cleanup. Wake its
            # holding timer as well so completed waits do not retain timer tasks.
            holding = waiter.session_controller.current_event
            if holding is not None:
                holding.set()
            processing = self._processing
            if processing is not None and not processing.done():
                processing.cancel()
                with suppress(asyncio.CancelledError):
                    await processing
            if USER_SESSIONS.get(self.session_id) is self:
                USER_SESSIONS.pop(self.session_id)
            self._active = False
            self._closed.set()

    async def regist_wait(self, handler: Callable, timeout: float = 30) -> Any:
        """Compatibility alias for the original misspelled API."""
        return await self.register_wait(handler, timeout)

    async def _deliver(self, input_data: Any) -> None:
        if self.future is None or self.future.done() or self._claimed:
            return
        self._claimed = True  # Claim synchronously, before another input can run.

        async def invoke():
            result = self.handler(input_data)
            return await result if inspect.isawaitable(result) else result

        processing = asyncio.create_task(invoke())
        self._processing = processing
        try:
            result = await processing
        except asyncio.CancelledError:
            # Cancellation of the incoming event should cancel the wait too.
            # Cancellation of only our callback (timeout/unload) must not cancel
            # the core pipeline task that delivered the message.
            if asyncio.current_task().cancelling():
                self.cancel()
                raise
            if not self.future.done():
                self.future.cancel()
        except Exception as exc:
            if not self.future.done():
                self.future.set_exception(exc)
        else:
            if not self.future.done():
                self._result = result
                self._native.session_controller.stop()
        finally:
            if self._processing is processing:
                self._processing = None

    @classmethod
    def trigger(cls, session_id: str, input_data: Any) -> asyncio.Task | None:
        """Manually deliver input; the returned task may optionally be awaited."""
        session = USER_SESSIONS.get(session_id)
        if session is None or session.future.done() or session._claimed:
            return None
        return asyncio.create_task(session._deliver(input_data))

    def cancel(self) -> None:
        """Cancel an active wait and its callback; safe to call repeatedly."""
        if self.future is not None and not self.future.done():
            self.future.cancel()
        if self._processing is not None and not self._processing.done():
            self._processing.cancel()

    @classmethod
    async def cancel_all(cls) -> None:
        """Drain only this plugin's waiters during unload/reload."""
        sessions = tuple(USER_SESSIONS.values())
        for session in sessions:
            session.cancel()
        if sessions:
            await asyncio.gather(*(session._closed.wait() for session in sessions))


def wait(session_id_param: str, timeout: float = 30):
    """Decorate a callback; pass the session ID/event as a keyword argument.

    Additional arguments are forwarded to the callback, allowing decorated
    instance methods and per-call context without shared mutable plugin state.
    """
    if not isinstance(session_id_param, str) or not session_id_param:
        raise ValueError("session_id_param 必须是非空字符串")

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if session_id_param not in kwargs:
                raise ValueError(f"缺少 session_id 参数 '{session_id_param}'")
            session = kwargs.pop(session_id_param)
            waiter = (
                SessionWaiter(session)
                if isinstance(session, str)
                else SessionWaiter.from_event(session)
            )

            async def handle(input_data):
                result = func(*args, input_data, **kwargs)
                return await result if inspect.isawaitable(result) else result

            return await waiter.register_wait(handle, timeout)

        return wrapper

    return decorator
