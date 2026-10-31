"""Run against installed AstrBot, or unmodified upstream source in offline QA.

ASTRBOT_SESSION_WAITER_SOURCE may point to the upstream session_waiter.py.
ASTRBOT_PROCESS_STAGE_SOURCE additionally enables the real ProcessStage test.
Only unrelated import dependencies are stubbed in source mode.
"""

import ast
import asyncio
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


class Event:
    def __init__(self, text="hello", origin="bot:GroupMessage:group", sender="u"):
        self.message_str = text
        self.unified_msg_origin = origin
        self.sender = sender
        self.stopped = False

    def get_sender_id(self):
        return self.sender

    def stop_event(self):
        self.stopped = True

    def get_extra(self, key):
        return []


source = os.environ.get("ASTRBOT_SESSION_WAITER_SOURCE")
if source:
    # Execute the upstream waiter implementation, without importing AstrBot's
    # unrelated adapters/providers/database dependencies.
    for name in (
        "astrbot",
        "astrbot.api",
        "astrbot.api.event",
        "astrbot.api.star",
        "astrbot.core",
        "astrbot.core.message",
        "astrbot.core.message.components",
        "astrbot.core.platform",
        "astrbot.core.utils",
    ):
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module
        parent, _, child = name.rpartition(".")
        if parent:
            setattr(sys.modules[parent], child, module)
    sys.modules["astrbot.api.event"].AstrMessageEvent = Event
    sys.modules["astrbot.core.platform"].AstrMessageEvent = Event
    sys.modules["astrbot.core.message.components"].BaseMessageComponent = object
    sys.modules["astrbot.api.star"].Star = type("Star", (), {})
    spec = importlib.util.spec_from_file_location(
        "astrbot.core.utils.session_waiter", source
    )
    native = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = native
    spec.loader.exec_module(native)
else:
    from astrbot.core.utils import session_waiter as native

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_waiter.custom_waiter import (
    USER_SESSIONS,
    SessionAlreadyWaitingError,
    SessionWaiter,
    get_session_id,
    wait,
)
from astrbot_plugin_waiter.main import Waiter


async def dispatch(event):
    """Use the same routing order as AstrBot ProcessStage."""
    for session_filter in tuple(native.FILTERS):
        key = session_filter.filter(event)
        session = native.USER_SESSIONS.get(key)
        if session and not session.session_controller.future.done():
            await native.SessionWaiter.trigger(key, event)
            event.stop_event()
            return True
    return False


class WaiterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await SessionWaiter.cancel_all()
        await asyncio.sleep(0)
        self.assertEqual(USER_SESSIONS, {})
        self.assertEqual(native.USER_SESSIONS, {})
        self.assertEqual(native.FILTERS, [])

    async def start(self, waiter, handler=None, timeout=1):
        task = asyncio.create_task(
            waiter.register_wait(handler or (lambda x: x), timeout)
        )
        await asyncio.sleep(0)
        return task

    async def test_native_routing_isolates_platform_group_and_sender(self):
        first = Event("one")
        others = [
            Event("two", "other:GroupMessage:group"),
            Event("three", "bot:GroupMessage:other"),
            Event("four", sender="other"),
            Event("five", "bot:FriendMessage:u"),
        ]
        events = [first, *others]
        tasks = [await self.start(SessionWaiter.from_event(e)) for e in events]
        for event in reversed(events):
            self.assertTrue(await dispatch(event))
        self.assertEqual(await asyncio.gather(*tasks), [e.message_str for e in events])
        self.assertFalse(await dispatch(Event("unmatched")))

    async def test_event_payload(self):
        event = Event()
        task = await self.start(SessionWaiter.from_event(event, receive_event=True))
        await dispatch(event)
        self.assertIs(await task, event)

    async def test_duplicate_does_not_overwrite_or_remove_original(self):
        event = Event()
        waiter = SessionWaiter.from_event(event)
        task = await self.start(waiter)
        with self.assertRaises(SessionAlreadyWaitingError):
            await SessionWaiter.from_event(event).register_wait(str)
        with self.assertRaises(SessionAlreadyWaitingError):
            await waiter.register_wait(str)
        self.assertIs(USER_SESSIONS[get_session_id(event)], waiter)
        await dispatch(event)
        self.assertEqual(await task, "hello")

    async def test_native_waiter_collision_is_preserved(self):
        event = Event()
        key = get_session_id(event)
        native_waiter = native.SessionWaiter(native.DefaultSessionFilter(), key, False)
        native_task = asyncio.create_task(native_waiter.register_wait(AsyncMock(), 1))
        await asyncio.sleep(0)
        try:
            with self.assertRaises(SessionAlreadyWaitingError):
                await SessionWaiter.from_event(event).register_wait(str)
            self.assertIs(native.USER_SESSIONS[key], native_waiter)
        finally:
            native_waiter.session_controller.current_event.set()
            native_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await native_task

    async def test_timeout_then_reuse(self):
        waiter = SessionWaiter.from_event(Event())
        with self.assertRaises(TimeoutError):
            await waiter.register_wait(str, timeout=0.01)
        task = await self.start(waiter)
        await dispatch(Event())
        self.assertEqual(await task, "hello")

    async def test_timeout_cancels_slow_callback_without_cancelling_pipeline(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def slow(text):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = await self.start(SessionWaiter.from_event(Event()), slow, 0.03)
        incoming = asyncio.create_task(dispatch(Event()))
        await started.wait()
        with self.assertRaises(TimeoutError):
            await task
        self.assertTrue(await incoming)
        self.assertTrue(cancelled.is_set())

    async def test_burst_inputs_execute_callback_once(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def handler(text):
            calls.append(text)
            started.set()
            await release.wait()
            return text

        event = Event()
        task = await self.start(SessionWaiter.from_event(event), handler)
        first = asyncio.create_task(dispatch(Event("first")))
        await started.wait()
        second = asyncio.create_task(dispatch(Event("second")))
        manual = SessionWaiter.trigger(get_session_id(event), "third")
        self.assertIsNone(manual)
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(await task, "first")
        self.assertEqual(calls, ["first"])

    async def test_callback_exception_propagates_and_cleans_up(self):
        async def fail(text):
            raise ValueError("bad input")

        task = await self.start(SessionWaiter.from_event(Event()), fail)
        await dispatch(Event())
        with self.assertRaisesRegex(ValueError, "bad input"):
            await task

    async def test_owner_cancellation(self):
        task = await self.start(SessionWaiter.from_event(Event()))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_incoming_event_cancellation(self):
        started = asyncio.Event()

        async def handler(text):
            started.set()
            await asyncio.Event().wait()

        task = await self.start(SessionWaiter.from_event(Event()), handler)
        incoming = asyncio.create_task(dispatch(Event()))
        await started.wait()
        incoming.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await incoming
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_unload_drains_waiters_and_preserves_unrelated_native_sessions(self):
        unrelated = native.SessionWaiter(
            native.DefaultSessionFilter(), "unrelated", False
        )
        unrelated_task = asyncio.create_task(unrelated.register_wait(AsyncMock(), 1))
        await asyncio.sleep(0)
        tasks = [
            await self.start(SessionWaiter.from_event(Event(sender=str(i))))
            for i in range(2)
        ]
        try:
            await Waiter.terminate(object())
            for task in tasks:
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertIs(native.USER_SESSIONS["unrelated"], unrelated)
        finally:
            unrelated.session_controller.current_event.set()
            unrelated_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await unrelated_task

    async def test_legacy_api_and_manual_trigger(self):
        with self.assertWarns(DeprecationWarning):
            waiter = SessionWaiter("hoyocos_u")
        task = asyncio.create_task(waiter.regist_wait(lambda text: int(text)))
        await asyncio.sleep(0)
        await dispatch(Event("5"))
        self.assertEqual(await task, 5)
        waiter = SessionWaiter("manual")
        task = await self.start(waiter)
        await SessionWaiter.trigger("manual", "value")
        self.assertEqual(await task, "value")
        self.assertIsNone(SessionWaiter.trigger("missing", "ignored"))

    async def test_decorator_function_and_bound_method(self):
        @wait("session_id")
        async def parse(text):
            return int(text)

        task = asyncio.create_task(parse(session_id=Event()))
        await asyncio.sleep(0)
        await dispatch(Event("3"))
        self.assertEqual(await task, 3)

        class Consumer:
            @wait("event")
            async def parse(self, text, *, offset):
                return int(text) + offset

        task = asyncio.create_task(Consumer().parse(event=Event(), offset=2))
        await asyncio.sleep(0)
        await dispatch(Event("3"))
        self.assertEqual(await task, 5)
        with self.assertRaises(ValueError):
            await parse()

    async def test_invalid_arguments_leave_no_registration(self):
        waiter = SessionWaiter("manual")
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                await waiter.register_wait(str, value)
        with self.assertRaises(TypeError):
            await waiter.register_wait(str, True)
        with self.assertRaises(TypeError):
            await waiter.register_wait(None)

    @unittest.skipUnless(
        os.environ.get("ASTRBOT_PROCESS_STAGE_SOURCE"),
        "requires upstream ProcessStage source",
    )
    async def test_actual_upstream_process_stage_consumes_followup(self):
        tree = ast.parse(
            Path(os.environ["ASTRBOT_PROCESS_STAGE_SOURCE"]).read_text("utf-8")
        )
        cls = next(
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "ProcessStage"
        )
        method = next(
            n
            for n in cls.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "process"
        )
        # Execute the unchanged upstream method; adapters and agent providers
        # are irrelevant to routing and do not need their runtime dependencies.
        scope = dict(
            FILTERS=native.FILTERS,
            USER_SESSIONS=native.USER_SESSIONS,
            SessionWaiter=native.SessionWaiter,
        )
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__", names=[ast.alias(name="annotations")], level=0
                ),
                method,
            ],
            type_ignores=[],
        )
        exec(
            compile(
                ast.fix_missing_locations(module), "upstream_process_stage", "exec"
            ),
            scope,
        )
        stage = types.SimpleNamespace(
            ctx=types.SimpleNamespace(
                astrbot_config={"provider_settings": {"enable": False}}
            )
        )
        event = Event("follow-up")
        task = await self.start(SessionWaiter.from_event(event))
        async for _ in scope["process"](stage, event):
            pass
        self.assertTrue(event.stopped)
        self.assertEqual(await task, "follow-up")


if __name__ == "__main__":
    unittest.main()
