"""异步路径测试：achat / achat_stream（假 SDK，asyncio.run 包装，不加 pytest-asyncio）。"""
import asyncio
from types import SimpleNamespace

import pytest

from my_agent_llm.config import Config
from my_agent_llm.models import Message, Response
from my_agent_llm.providers.anthropic import AnthropicProvider
from my_agent_llm.providers.openai import OpenAIProvider
from tests.fake_anthropic import make_anthropic_response, make_block
from tests.fakes import make_openai_response


class FakeAsyncOpenAI:
    """替身：async chat.completions.create 按脚本返回，记录请求。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.chat.completions.create = self.create  # 接通 async_client.chat.completions.create → self.create

    @property
    def chat(self):
        return self

    class completions:
        @staticmethod
        async def create(**kwargs):
            raise NotImplementedError  # 由实例方法覆盖

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeAsyncStream:
    """异步流替身：__aiter__/__anext__ 按脚本产块。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        self._it = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeAsyncAnthropic:
    """替身：async messages.create / messages.stream 按脚本返回，记录请求。"""

    def __init__(self, responses, stream_response=None):
        self.responses = list(responses)
        self.stream_response = stream_response
        self.calls: list[dict] = []
        self.messages.create = self.create
        self.messages.stream = self.stream

    class messages:
        @staticmethod
        async def create(**kwargs):
            raise NotImplementedError  # 由实例方法覆盖

        @staticmethod
        def stream(**kwargs):
            raise NotImplementedError  # 由实例方法覆盖

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return self.stream_response


class FakeAsyncAnthropicStream:
    """替身：async with messages.stream(...) 的上下文管理器。"""

    def __init__(self, texts, final):
        self._texts = list(texts)
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def _gen():
            for t in self._texts:
                yield t
        return _gen()

    async def get_final_message(self):
        return self._final


def test_openai_achat():
    """OpenAI achat → Response。"""
    p = OpenAIProvider(
        Config(api_key="test"),
        client=FakeAsyncOpenAI([]),  # 占位：achat 只走 async_client
        async_client=FakeAsyncOpenAI([make_openai_response(content="hello")]),
    )
    resp = asyncio.run(p.achat([Message(role="user", content="hi")], model="gpt-4.1-mini"))
    assert isinstance(resp, Response)
    assert resp.content == "hello"
    assert resp.model == "gpt-4.1-mini"


def test_openai_achat_stream():
    """OpenAI achat_stream → 逐 delta 文本块；usage-only 末块（choices 为空）跳过。"""
    chunks = [
        SimpleNamespace(id="1", choices=[SimpleNamespace(delta=SimpleNamespace(content="a"), finish_reason=None)]),
        SimpleNamespace(id="2", choices=[SimpleNamespace(delta=SimpleNamespace(content="b"), finish_reason="stop")]),
        SimpleNamespace(id="3", choices=[]),  # usage-only 末块
    ]
    p = OpenAIProvider(
        Config(api_key="test"),
        client=FakeAsyncOpenAI([]),
        async_client=FakeAsyncOpenAI([FakeAsyncStream(chunks)]),
    )

    async def collect():
        return [c async for c in p.achat_stream([Message(role="user", content="hi")], model="gpt-4.1-mini")]

    out = asyncio.run(collect())
    assert [c.content for c in out] == ["a", "b"]


def test_openai_achat_stream_aggregates_tool_calls():
    """OpenAI achat_stream → 末块聚合 tool_calls + usage。"""
    chunks = [
        SimpleNamespace(id="1", choices=[SimpleNamespace(
            delta=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    index=0, id="call_1",
                    function=SimpleNamespace(name="get_weather", arguments=""),
                )],
            ),
            finish_reason=None,
        )], usage=None),
        SimpleNamespace(id="2", choices=[SimpleNamespace(
            delta=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    index=0, id=None,
                    function=SimpleNamespace(name=None, arguments='{"city":"Tokyo"}'),
                )],
            ),
            finish_reason="tool_calls",
        )], usage=None),
        SimpleNamespace(id="3", choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)),
    ]
    p = OpenAIProvider(
        Config(api_key="test"),
        client=FakeAsyncOpenAI([]),
        async_client=FakeAsyncOpenAI([FakeAsyncStream(chunks)]),
    )

    async def collect():
        return [c async for c in p.achat_stream([Message(role="user", content="hi")], model="gpt-4.1-mini")]

    out = asyncio.run(collect())
    assert [c.content for c in out] == [""]
    assert out[0].tool_calls == [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":"Tokyo"}'},
    }]
    assert out[0].usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert out[0].finish_reason == "tool_calls"  # 末块透传循环内捕获的 finish_reason


def test_openai_achat_missing_async_client():
    """async_client 未注入 → achat 抛 RuntimeError（fail-loud）。"""
    p = OpenAIProvider(Config(api_key="test"), client=FakeAsyncOpenAI([]))
    with pytest.raises(RuntimeError, match="async_client"):
        asyncio.run(p.achat([Message(role="user", content="hi")], model="gpt-4.1-mini"))


def test_anthropic_achat():
    """Anthropic achat → Response。"""
    p = AnthropicProvider(
        Config(api_key="test"),
        client=FakeAsyncAnthropic([]),
        async_client=FakeAsyncAnthropic([make_anthropic_response(text="hello")]),
    )
    resp = asyncio.run(p.achat([Message(role="user", content="hi")], model="claude-sonnet-4-5"))
    assert resp.content == "hello"
    assert resp.model == "claude-sonnet-4-5"


def test_anthropic_achat_stream():
    """Anthropic achat_stream → 逐文本块 + 末块（usage + finish_reason）。"""
    final = make_anthropic_response(text="end", stop="end_turn")
    p = AnthropicProvider(
        Config(api_key="test"),
        client=FakeAsyncAnthropic([]),
        async_client=FakeAsyncAnthropic(
            [], stream_response=FakeAsyncAnthropicStream(texts=["a", "b"], final=final)
        ),
    )

    async def collect():
        return [c async for c in p.achat_stream([Message(role="user", content="hi")], model="claude-sonnet-4-5")]

    out = asyncio.run(collect())
    assert [c.content for c in out] == ["a", "b", ""]
    last = out[-1]
    assert last.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert last.finish_reason == "end_turn"


def test_anthropic_achat_stream_reasoning():
    """末块补发：reasoning → metadata.reasoning_content。"""
    final = make_anthropic_response(text="end")
    final.content.append(make_block("thinking", thinking="let me think"))
    p = AnthropicProvider(
        Config(api_key="test"),
        client=FakeAsyncAnthropic([]),
        async_client=FakeAsyncAnthropic(
            [], stream_response=FakeAsyncAnthropicStream(texts=[], final=final)
        ),
    )

    async def collect():
        return [c async for c in p.achat_stream([Message(role="user", content="hi")], model="claude-sonnet-4-5")]

    out = asyncio.run(collect())
    assert out[-1].metadata == {"reasoning_content": "let me think"}


def test_anthropic_achat_missing_async_client():
    """async_client 未注入 → achat 抛 RuntimeError（fail-loud）。"""
    p = AnthropicProvider(Config(api_key="test"), client=FakeAsyncAnthropic([]))
    with pytest.raises(RuntimeError, match="async_client"):
        asyncio.run(p.achat([Message(role="user", content="hi")], model="claude-sonnet-4-5"))
