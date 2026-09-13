"""假 SDK 替身：按脚本返回响应，记录请求。"""
from types import SimpleNamespace


def _to_sdk_tool_calls(tool_calls):
    """wire 形状的 tool_calls → fake SDK 对象（模拟真实 SDK 的解析结果）。"""
    if not tool_calls:
        return None
    return [
        SimpleNamespace(
            id=tc["id"],
            type=tc.get("type", "function"),
            function=SimpleNamespace(
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"],
            ),
        )
        for tc in tool_calls
    ]


def make_openai_response(content: str = "hi", tool_calls=None, finish="stop", model="gpt-4.1-mini"):
    """构造一个 fake OpenAI chat.completions.create 响应。"""
    return SimpleNamespace(
        id="fake-id",
        model=model,
        choices=[
            SimpleNamespace(
                finish_reason=finish,
                message=SimpleNamespace(content=content, tool_calls=_to_sdk_tool_calls(tool_calls)),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


class FakeOpenAI:
    """替身：chat.completions.create 按脚本返回，记录请求。"""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.chat.completions.create = self.create  # 接通 client.chat.completions.create → self.create

    @property
    def chat(self):
        return self

    class completions:
        @staticmethod
        def create(**kwargs):
            raise NotImplementedError  # 由实例方法覆盖

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)
