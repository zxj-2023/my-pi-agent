# pyright: reportAttributeAccessIssue=false, reportMissingImports=false
"""LLM 门面 astream_events 高阶流式事件流测试。"""

import asyncio

from my_agent_llm import LLM, Config
from my_agent_llm.events import (
    StreamDoneEvent,
    StreamStartEvent,
    TextDeltaEvent,
)
from my_agent_llm.models import (
    Message,
    Response,
    StreamChunk,
)


class MockSignal:
    def __init__(self, cancelled: bool = False):
        self._cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self):
        self._cancelled = True


def test_llm_astream_events_normal():
    """测试 LLM 门面正确透传 astream_events 事件。"""
    llm = LLM(config=Config(provider="openai", api_key="k", model="test-model"))

    class FakeProvider:
        async def astream_events(
            self, messages, *, model, tools=None, signal=None, **kwargs
        ):
            _ = (messages, model, tools, signal, kwargs)
            yield StreamStartEvent(partial=Message(role="assistant", content=""))
            yield TextDeltaEvent(
                delta="Hello", partial=Message(role="assistant", content="Hello")
            )
            yield StreamDoneEvent(
                message=Message(role="assistant", content="Hello"),
                usage={"total_tokens": 5},
            )

    llm._provider = FakeProvider()  # type: ignore[assignment]

    async def run():
        events = []
        async for ev in llm.astream_events([Message(role="user", content="hi")]):
            events.append(ev)
        assert len(events) == 3
        assert isinstance(events[0], StreamStartEvent)
        assert isinstance(events[1], TextDeltaEvent)
        assert isinstance(events[2], StreamDoneEvent)
        assert events[2].message.content == "Hello"

    asyncio.run(run())


def test_provider_default_astream_events_wrapping():
    """测试 Provider 基类默认 astream_events 使用 StreamAccumulator 包装 achat_stream。"""
    from my_agent_llm.providers._base import Provider

    class TestProvider(Provider):
        def __init__(self, config):
            self.config = config

        def chat(self, messages, *, model, tools=None, **kwargs):
            _ = (messages, model, tools, kwargs)
            raise NotImplementedError

        def stream(self, messages, *, model, tools=None, **kwargs):
            _ = (messages, model, tools, kwargs)
            raise NotImplementedError

        async def achat(self, messages, *, model, tools=None, **kwargs):
            _ = (messages, model, tools, kwargs)
            raise NotImplementedError

        async def achat_stream(
            self, messages, *, model, tools=None, **kwargs
        ):
            _ = (messages, tools, kwargs)
            yield StreamChunk(content="chunk1")
            yield StreamChunk(content="chunk2")
            resp = Response(
                content="chunk1chunk2", model=model, usage={"total_tokens": 12}
            )
            yield StreamChunk(content="", usage={"total_tokens": 12}, response=resp)

    tp = TestProvider(Config(provider="openai", api_key="test", model="test-model"))

    async def run():
        events = []
        async for ev in tp.astream_events(
            [Message(role="user", content="hi")], model="test-model"
        ):
            events.append(ev)

        assert len(events) == 4
        assert isinstance(events[0], StreamStartEvent)
        assert isinstance(events[1], TextDeltaEvent)
        assert events[1].delta == "chunk1"
        assert isinstance(events[2], TextDeltaEvent)
        assert events[2].delta == "chunk2"
        assert isinstance(events[3], StreamDoneEvent)
        assert events[3].message.content == "chunk1chunk2"
        assert events[3].usage == {"total_tokens": 12}

    asyncio.run(run())
