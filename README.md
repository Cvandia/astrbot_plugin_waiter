# astrbot_plugin_waiter

面向插件开发者的一次性输入等待器。v2.0.0 接入 AstrBot 原生会话管道，保留旧版的返回值处理方式。

## 环境与安装

- AstrBot `>=4.29.4,<5`，Python `>=3.12`。本次适配基准是 2026-10-31 发布的 [v4.29.4](https://github.com/AstrBotDevs/AstrBot/releases/tag/v4.29.4)。后续 4.x 版本仍需回归验证。
- 将本目录放到 `AstrBot/data/plugins/astrbot_plugin_waiter`，目录中应直接包含 `main.py` 和 `metadata.yaml`，然后重载插件。没有额外运行时依赖。
- 通过仓库 URL 安装时以默认分支为准；如需安装未合并分支，请下载对应分支的源码 ZIP 并本地安装。

## 推荐用法

在另一个插件的 `main.py` 中使用：

```python
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Star

from ..astrbot_plugin_waiter.custom_waiter import (
    SessionAlreadyWaitingError,
    SessionWaiter,
)


class Example(Star):
    @filter.command("数量")
    async def count(self, event: AstrMessageEvent):
        async def parse(text: str) -> int:
            value = int(text)
            if not 1 <= value <= 5:
                raise ValueError("请输入 1–5 之间的整数")
            return value

        try:
            yield event.plain_result("请输入 1–5 之间的整数：")
            value = await SessionWaiter.from_event(event).register_wait(
                parse, timeout=30
            )
            yield event.plain_result(f"输入的参数为：{value}")
        except TimeoutError:
            yield event.plain_result("超时未输入，已退出")
        except SessionAlreadyWaitingError:
            yield event.plain_result("当前会话正在等待输入")
        except ValueError:
            yield event.plain_result("输入不合法，本次等待已结束，请重新发送 /数量")
        finally:
            event.stop_event()
```

每次调用独立保存结果，不要用插件实例上的 `self.args` 或 `self.waiter` 保存不同用户的临时输入。等待器按平台实例、统一消息来源和发送者 ID 隔离，即使 AstrBot 配置为群共享会话，也只接收发起人的输入。

注册完成后，下一条匹配的输入由 AstrBot 核心接管，不需要再次 @ 或输入唤醒前缀，也不会继续触发普通插件或默认 Agent。白名单、会话开关、限流和安全检查仍由框架执行。等待窗口内发送的其他命令也会作为本次输入处理。

这是一次性等待器：回调成功时返回回调结果；回调抛出异常时结束等待并将异常传给调用方。超时包括回调执行时间。需要多轮校验、历史消息链或 `controller.keep()` 时，请直接使用 [AstrBot 原生会话控制](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/docs/zh/dev/star/guides/session-control.md)。

## 装饰器

```python
from ..astrbot_plugin_waiter.custom_waiter import wait


@wait("session_id", timeout=20)
async def parse_count(text: str) -> int:
    return int(text)


# 在异步 handler 中调用；传入事件会自动生成隔离后的会话 ID。
value = await parse_count(session_id=event)
```

同样支持绑定实例方法和额外关键字参数，回调始终接收用户输入，`session_id` 参数只用于路由，不传给回调。异步回调和普通同步回调均可使用；同步回调应快速返回，阻塞操作应交给 `asyncio.to_thread()`。

## 完整事件与手动触发

```python
async def read_event(reply: AstrMessageEvent):
    # 可使用 reply.get_messages()、reply.send() 等。
    return reply.message_str


value = await SessionWaiter.from_event(event, receive_event=True).register_wait(
    read_event
)
```

保留 `SessionWaiter.trigger(session_id, input_data)` 手动投递接口，返回可选的 `asyncio.Task`，无有效等待器时返回 `None`。自定义字符串 ID 只用于手动投递；自动事件路由请使用 `from_event(event)` 或 `get_session_id(event)`。

回调不应吞掉 `asyncio.CancelledError`。等待被取消、超时或本插件卸载时，会取消正在执行的回调并清理会话。`waiter.cancel()` 可主动取消等待；调用方会收到 `asyncio.CancelledError`。

## 从 v1 迁移

| v1 用法 | v2 建议 |
| --- | --- |
| `SessionWaiter(f"hoyocos_{event.get_sender_id()}")` | `SessionWaiter.from_event(event)` |
| `waiter.regist_wait(handler, timeout=30)` | `waiter.register_wait(handler, timeout=30)`；原拼写仍可用 |
| `await decorated(session_id=session_id)` | `await decorated(session_id=event)` |
| 重复注册会覆盖旧会话 | 抛出 `SessionAlreadyWaitingError`，保留原等待器 |
| 依赖 `handle_message()` 返回 `True` 阻断消息 | 交由原生会话管道消费，无需额外监听器 |

旧的 `hoyocos_<sender_id>` 字符串仍可自动匹配，并产生 `DeprecationWarning`，其跨群、跨平台路由行为也保持原样。迁移到 `from_event(event)` 后才会启用严格隔离。`USER_SESSIONS` 仍可导入用于查看活动等待器，但不要直接修改它。

## 验证

安装了目标版本 AstrBot 的环境可执行：

```sh
python -m unittest discover -s tests -v
```

也可针对固定版本的上游源码执行隔离验证：

```sh
python tests/run_upstream.py
```

第二个命令下载并校验 v4.29.4 原始文件，然后执行 15 项回归测试，其中包括未修改的原生等待器实现与 `ProcessStage.process` 消息处理方法。与会话无关的导入依赖使用替身；这不等同于启动完整 AstrBot，也未覆盖 QQ、Telegram 等真实平台联调。

## 参考

- [AstrBot v4.29.4 会话实现](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/core/utils/session_waiter.py)
- [消息处理阶段](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/astrbot/core/pipeline/process_stage/stage.py)
- [Python 版本要求](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.4/pyproject.toml)
