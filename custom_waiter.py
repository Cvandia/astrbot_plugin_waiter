import asyncio
import functools
from typing import Dict, Any, Callable, Awaitable

USER_SESSIONS: Dict[str, "SessionWaiter"] = {}  # 存储 SessionWaiter 实例


class SessionWaiter:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.future = asyncio.Future()
        self.timeout_task: asyncio.Task | None = None
        self.handler: Callable[[str], Awaitable[Any]] | None = None  # 处理函数

    async def regist_wait(
        self,
        handler: Callable[[str], Awaitable[Any]],
        timeout: int = 30,
    ) -> Any:
        """等待外部输入并处理"""
        self.handler = handler
        USER_SESSIONS[self.session_id] = self
        self.timeout_task = asyncio.create_task(self._handle_timeout(timeout))

        try:
            return await self.future
        finally:
            self._cleanup()

    async def _handle_timeout(self, timeout: int):
        try:
            await asyncio.sleep(timeout)
            if not self.future.done():
                self.future.set_exception(TimeoutError("等待超时"))
        except asyncio.CancelledError:
            pass  # 避免报错
        finally:
            self._cleanup()

    def _cleanup(self):
        """清理会话"""
        USER_SESSIONS.pop(self.session_id, None)
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()

    @classmethod
    def trigger(cls, session_id: str, input_data: str):
        """外部输入触发会话处理"""
        session = USER_SESSIONS.get(session_id)
        if not session or session.future.done():
            return

        async def _run():
            try:
                result = await session.handler(input_data)
                if not session.future.done():
                    session.future.set_result(result)
            except Exception as e:
                if not session.future.done():
                    session.future.set_exception(e)

        asyncio.create_task(_run())


def wait(session_id_param: str, timeout: int = 30):
    """
    装饰器：自动将函数注册为 SessionWaiter 处理函数，并等待外部输入触发执行。

    :param session_id_param: 用于从参数中获取 session_id 的参数名称
    :param timeout: 超时时间（秒）
    """

    def decorator(func: Callable[[str], Awaitable[Any]]):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            session_id = kwargs.get(session_id_param)
            if not session_id:
                raise ValueError(f"缺少 session_id 参数 '{session_id_param}'")

            waiter = SessionWaiter(session_id)
            return await waiter.regist_wait(func, timeout)

        return wrapper

    return decorator
