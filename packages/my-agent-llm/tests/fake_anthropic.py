"""假 Anthropic SDK：messages.create 按脚本返回 content blocks。"""
from types import SimpleNamespace


def make_block(block_type: str, **kwargs):
    return SimpleNamespace(type=block_type, **kwargs)


def make_anthropic_response(text: str | None = None, tool_uses=None, stop="end_turn"):
    """构造 fake messages.create 响应（content blocks）。"""
    content = []
    if text:
        content.append(make_block("text", text=text))
    for tu in tool_uses or []:
        content.append(make_block("tool_use", id=tu["id"], name=tu["name"], input=tu["input"]))
    return SimpleNamespace(
        id="fake-ant-id",
        model="claude-sonnet-4-5",
        content=content,
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class FakeAnthropic:
    """替身：messages.create 按脚本返回，记录请求。"""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.messages.create = self.create  # 接通 client.messages.create → self.create

    class messages:
        @staticmethod
        def create(**kwargs):
            raise NotImplementedError  # 由实例覆盖

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)
