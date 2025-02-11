<div align="center">

# astrbot_plugin_waiter

<a href="https://v2.nonebot.dev/store">
<img src="https://count.getloli.com/get/@astrbot_plugin_waiter?theme=booru-lewd"></a>

_⭐基于AstrBot帮助开发者管理对话的插件⭐_

<a href="https://www.python.org/downloads/release/python-310/">
    <img src="https://img.shields.io/badge/python-3.10+-blue"></a>
<a href="https://qm.qq.com/q/SL6m4KdFe4">
    <img src="https://img.shields.io/badge/QQ-1141538825-yellow"></a>
<a href="https://github.com/Cvandia/pdm-project-template/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-blue"></a>
<a href="https://github.com/Soulter/AstrBot">
    <img src="https://img.shields.io/badge/AstrBot-3.4.23+-red"></a>
<a href="https://github.com/Cvandia/astrbot_plugin_waiter/blob/main/.github/workflows/ruff-check.yml">
    <img src="https://github.com/Cvandia/astrbot_plugin_waiter/actions/workflows/ruff-check.yml/badge.svg?branch=main"></a>

**中文简体**

</div>

---

## 使用

1. 添加插件到`astrbot/data/plugins`目录下，并重启AstrBot。
2. 或者使用管理终端添加插件。

以下是一个简要的使用示例：
* 带装饰器的示例
```python
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from ..astrbot_plugin_waiter.custom_waiter import SessionWaiter, wait # 导入自定义等待器，需要先安装

@register(
    "plugin",
    "Cvandia",
    "dec",
    "1.0.0",
    "repo_url",
)
class Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.waiter = None  
        self.args = None # 存储用户输入的参数
    
    @filter.command("test")
    async def test(self, event: AstrMessageEvent)
        sender_id = event.get_sender_id()
        session_id = f"hoyocos_{sender_id}"
        if not self.args:
            # 提示输入
            yield event.plain_result("请输入参数：")
            @wait("session_id", timeout=20) # 创建一个等待器，等待用户输入
            async def waiter_handler(input_data: str): # 创建一个等待器处理函数
                try:
                    return max(1, min(int(input_data), 5))
                except Exception as e:
                    logger.error(f"Error in waiter handler: {e}")
                    return "输入的数量不合法，请输入1-5之间的整数"
            try:
                user_input = await waiter_handler(session_id=session_id)
            except TimeoutError:
                yield event.plain_result("超时未输入，已退出")
            
            self.args = user_input
            yield event.plain_result(f"输入的参数为：{self.args}")
            ...
```

* 函数式示例
```python
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from ..astrbot_plugin_waiter.custom_waiter import SessionWaiter # 导入自定义等待器，需要先安装

@register(
    "plugin",
    "Cvandia",
    "func",
    "1.0.0",
    "repo_url",
)
class Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.waiter = None
        self.args = None

    @filter.command("test")
    async def test(self, event: AstrMessageEvent):
        sender_id = event.get_sender_id()
        session_id = f"hoyocos_{sender_id}"
        if not self.args:
            yield event.plain_result("请输入参数：") # 提示输入
            self.waiter = SessionWaiter(session_id) # 创建一个等待器
        try:
            user_input = await self.waiter.regist_wait(
                self._validate_count_input, timeout=30
            )
            yield event.plain_result(count)
        except TimeoutError:
            yield event.plain_result("超时未输入，已退出")
        
        self.args = user_input
        yield event.plain_result(f"输入的参数为：{self.args}")
        ...


    async def _validate_count_input(self, input_str: str) -> int:
    """验证用户输入的图片数量"""
    try:
        return max(1, min(int(input_str), 5))
    except ValueError:
        return "输入的数量不合法，请输入1-5之间的整数"
```

## 💝 特别鸣谢

- [x] [AstrBot](https://github.com/Soulter/AstrBot): 本项目的基础，非常好用的基于LLM聊天的机器人框架。
- [x] [@qxdn](https://github.com/qxdn):感谢qxdn的[博客文章](https://qianxu.run/2021/11/12/mihoyo-bbs-crawler/)

### 感谢以下开发者

<a href="https://github.com/Cvandia/astrbot_plugin_waiter/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Cvandia/astrbot_plugin_waiter&max=100" alt="contributors" />
</a>

# 支持

[帮助文档](https://astrbot.soulter.top/center/docs/%E5%BC%80%E5%8F%91/%E6%8F%92%E4%BB%B6%E5%BC%80%E5%8F%91/
)
