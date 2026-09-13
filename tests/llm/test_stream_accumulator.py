"""StreamAccumulator 统一累加器单元测试（对标 Tau stream.py）。"""

import asyncio

from my_agent_llm.events import (  # pyright: ignore[reportMissingImports]
    StreamDoneEvent,
    StreamErrorEvent,
    StreamStartEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallDoneEvent,
)
from my_agent_llm.models import (  # pyright: ignore[reportMissingImports]
    Response,
    StreamChunk,
    ToolCall,
)
from my_agent_llm.stream import (  # pyright: ignore[reportMissingImports]
    StreamAccumulator,
)


class MockSignal:
    def __init__(self, cancelled: bool = False):
        self._cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self):
        self._cancelled = True


def test_accumulator_text_stream():
    """验证文本流正常发射 Start -> TextDelta -> Done。"""

    async def run():
        async def fake_chunks():
            yield StreamChunk(content="Hello")
            yield StreamChunk(content=" world")
            resp = Response(content="Hello world", model="gpt-4o", usage={"total_tokens": 10})
            yield StreamChunk(content="", usage={"total_tokens": 10}, response=resp)

        acc = StreamAccumulator()
        events = [ev async for ev in acc.stream(fake_chunks())]

        assert len(events) == 4
        # 1. Start Event
        assert isinstance(events[0], StreamStartEvent)
        assert events[0].partial.content == ""

        # 2. Delta 1
        assert isinstance(events[1], TextDeltaEvent)
        assert events[1].delta == "Hello"
        assert events[1].partial.content == "Hello"

        # 3. Delta 2
        assert isinstance(events[2], TextDeltaEvent)
        assert events[2].delta == " world"
        assert events[2].partial.content == "Hello world"

        # 4. Done Event
        assert isinstance(events[3], StreamDoneEvent)
        assert events[3].message.content == "Hello world"
        assert events[3].usage == {"total_tokens": 10}

    asyncio.run(run())


def test_accumulator_tool_call_and_thinking():
    """验证思维链增量与结构化 ToolCall 增量。"""
    tc = ToolCall(id="call_1", name="search", args={"q": "tau"})

    async def run():
        async def fake_chunks():
            # 思维链 chunk
            yield StreamChunk(content="", metadata={"reasoning_content": "let me think"})
            # 工具调用 chunk
            yield StreamChunk(content="", tool_calls=[tc])
            resp = Response(
                content="",
                model="deepseek-reasoner",
                tool_calls=[tc],
                reasoning_content="let me think",
            )
            yield StreamChunk(content="", response=resp)

        acc = StreamAccumulator()
        events = [ev async for ev in acc.stream(fake_chunks())]

        assert isinstance(events[0], StreamStartEvent)
        assert isinstance(events[1], ThinkingDeltaEvent)
        assert events[1].delta == "let me think"
        assert (events[1].partial.metadata or {}).get("reasoning_content") == "let me think"

        assert isinstance(events[2], ToolCallDoneEvent)
        assert events[2].tool_call == tc

        assert isinstance(events[3], StreamDoneEvent)
        assert (events[3].message.metadata or {}).get("tool_calls") == [tc.model_dump()]

    asyncio.run(run())


def test_accumulator_cancellation():
    """验证中途取消安全捕获，发射 StreamErrorEvent(stop_reason='cancelled')。"""
    signal = MockSignal()

    async def run():
        async def fake_chunks():
            yield StreamChunk(content="Partial content")
            signal.cancel()
            yield StreamChunk(content="Should not matter")

        acc = StreamAccumulator()
        events = [ev async for ev in acc.stream(fake_chunks(), signal=signal)]

        assert isinstance(events[0], StreamStartEvent)
        assert isinstance(events[1], TextDeltaEvent)
        # 取消后发射 StreamErrorEvent
        last_event = events[-1]
        assert isinstance(last_event, StreamErrorEvent)
        assert last_event.stop_reason == "cancelled"
        assert "Partial content" in last_event.error.content
        assert (last_event.error.metadata or {}).get("stop_reason") == "cancelled"

    asyncio.run(run())


def test_accumulator_never_throw_on_exception():
    """验证底层网络异常被安全拦截，Never-Throw 封装为 StreamErrorEvent。"""

    async def run():
        async def broken_chunks():
            yield StreamChunk(content="Before error")
            raise ConnectionResetError("Connection lost")

        acc = StreamAccumulator()
        events = [ev async for ev in acc.stream(broken_chunks())]

        assert isinstance(events[0], StreamStartEvent)
        assert isinstance(events[1], TextDeltaEvent)
        last_event = events[-1]
        assert isinstance(last_event, StreamErrorEvent)
        assert last_event.stop_reason == "error"
        assert "Connection lost" in last_event.error.content
        assert (last_event.error.metadata or {}).get("stop_reason") == "error"
        assert isinstance(last_event.exc, ConnectionResetError)

    asyncio.run(run())


def test_accumulator_preserves_tool_calls_stop_reason():
    """验证当存在 tool_calls 时，StreamDoneEvent 的 stop_reason 保持 'tool_calls' 而非被覆盖为 'stop'。"""
    tc = ToolCall(id="call_1", name="search", args={"q": "tau"})

    async def run():
        async def fake_chunks():
            resp = Response(
                content="",
                model="gpt-4o",
                tool_calls=[tc],
                finish_reason="tool_calls",
            )
            yield StreamChunk(content="", tool_calls=[tc], response=resp)

        acc = StreamAccumulator()
        events = [ev async for ev in acc.stream(fake_chunks())]
        done = events[-1]
        assert isinstance(done, StreamDoneEvent)
        assert (done.message.metadata or {}).get("stop_reason") == "tool_calls"

    asyncio.run(run())
