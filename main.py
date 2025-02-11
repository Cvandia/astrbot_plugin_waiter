
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from .custom_waiter import SessionWaiter, USER_SESSIONS

@register(
    "astrbot_plugin_waiter",
    "Cvandia",
    "一个用于等待用户输入的插件",
    "1.0.0",
    "https://github.com/Cvandia/astrbot_plugin_waiter",
)
class Waiter(Star):
    """等待器插件"""

    def __init__(self, context: Context):
        super().__init__(context)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_message(self, event: AstrMessageEvent):
        session_id = f"hoyocos_{event.get_sender_id()}"
        if session_id in USER_SESSIONS:
            SessionWaiter.trigger(session_id, event.message_str) # 目前仅支持字符串消息
            return True  # 标记已由会话处理
        return False
