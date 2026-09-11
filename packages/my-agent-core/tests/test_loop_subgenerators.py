"""Unit tests for loop sub-generators in loop.py.

Tests the 3 dedicated sub-generators/helpers in isolation:
1. _assistant_turn
2. _synthesize_interrupted_tool_calls
3. _execute_tools_turn
"""

import pytest
from my_agent_llm import Message, StreamChunk

from my_agent_core.agent import CancellationToken
from my_agent_core.events import (
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
)
from my_agent_core.hooks import (  # pyright: ignore[reportMissingImports]
    HookResult,
    ToolCallHook,
    ToolResultHook,
)
from my_agent_core.loop import (
    _assistant_turn,
    _execute_tools_turn,
    _synthesize_interrupted_tool_calls,
)
from my_agent_core.registry import ToolRegistry, tool
from my_agent_core.tool_history import _INTERRUPTED_TOOL_RESULT


class FakeStreamLLM:
    """Fake LLM supporting achat_stream."""

    def __init__(self, chunks: list[StreamChunk] | None = None) -> None:
        self.chunks = chunks or [
            StreamChunk(content="Hello "),
            StreamChunk(content="world!"),
        ]

    async def achat_stream(self, *, messages, tools=None, model=None, **kwargs):
        _ = (messages, tools, model, kwargs)
        for chunk in self.chunks:
            yield chunk


# ─────────────────────────────────────────────────────────────
# 1. _assistant_turn Tests
# ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_assistant_turn_streaming():
    llm = FakeStreamLLM()
    events = []
    async for ev in _assistant_turn(
        llm=llm,
        view=[Message(role="user", content="hi")],
        tool_schemas=[],
        model=None,
        signal=None,
        context_manager=None,
    ):
        events.append(ev)

    assert len(events) >= 3
    # Check updates
    updates = [e for e in events if isinstance(e, MessageUpdate)]
    assert len(updates) == 2
    assert updates[0].message.content == "Hello "
    assert updates[1].message.content == "Hello world!"

    # Check start, updates, and termination sequence
    assert isinstance(events[0], MessageStart)
    assert events[0].message.role == "assistant"
    assert isinstance(events[-1], MessageEnd)
    assert events[-1].message.content == "Hello world!"


@pytest.mark.anyio
async def test_assistant_turn_with_usage_and_context_manager():
    class DummyContextManager:
        def __init__(self) -> None:
            self.recorded = None

        def record_usage(self, usage: dict) -> None:
            self.recorded = usage

    cm = DummyContextManager()
    llm = FakeStreamLLM(
        [
            StreamChunk(
                content="reply", usage={"prompt_tokens": 20, "completion_tokens": 10}
            )
        ]
    )
    events = []
    async for ev in _assistant_turn(
        llm=llm,
        view=[],
        tool_schemas=[],
        model=None,
        signal=None,
        context_manager=cm,
    ):
        events.append(ev)

    assert cm.recorded == {"prompt_tokens": 20, "completion_tokens": 10}
    end_msg = events[-1].message
    assert end_msg.content == "reply"


@pytest.mark.anyio
async def test_assistant_turn_cancellation():
    token = CancellationToken()

    class InfiniteStreamLLM:
        async def achat_stream(self, *, messages, tools=None, model=None, **kwargs):
            _ = (messages, tools, model, kwargs)
            yield StreamChunk(content="part1")
            token.cancel()
            yield StreamChunk(content="part2")

    events = []
    async for ev in _assistant_turn(
        llm=InfiniteStreamLLM(),
        view=[],
        tool_schemas=[],
        model=None,
        signal=token,
        context_manager=None,
    ):
        events.append(ev)

    end_ev = [e for e in events if isinstance(e, MessageEnd)][0]
    assert end_ev.message.metadata is not None
    assert end_ev.message.metadata.get("stop_reason") == "cancelled"


@pytest.mark.anyio
async def test_assistant_turn_never_throw_on_exception():
    class BrokenLLM:
        async def achat_stream(self, *, messages, tools=None, model=None, **kwargs):
            _ = (messages, tools, model, kwargs)
            yield StreamChunk(content="before failure")
            raise RuntimeError("API connection broke")

    events = []
    async for ev in _assistant_turn(
        llm=BrokenLLM(),
        view=[],
        tool_schemas=[],
        model=None,
        signal=None,
        context_manager=None,
    ):
        events.append(ev)

    # Must finish with MessageStart + MessageEnd containing error without raising
    end_ev = [e for e in events if isinstance(e, MessageEnd)][0]
    assert "Error during model stream: API connection broke" in end_ev.message.content
    assert end_ev.message.metadata is not None
    assert end_ev.message.metadata.get("stop_reason") == "error"


# ─────────────────────────────────────────────────────────────
# 3. _synthesize_interrupted_tool_calls Tests
# ─────────────────────────────────────────────────────────────


def test_synthesize_interrupted_tool_calls():
    tool_calls = [
        {"id": "call_1", "function": {"name": "bash", "arguments": "{}"}},
        {"id": "call_2", "function": {"name": "read", "arguments": "{}"}},
    ]
    messages = _synthesize_interrupted_tool_calls(tool_calls)
    assert len(messages) == 2

    assert messages[0].role == "tool"
    assert messages[0].content == _INTERRUPTED_TOOL_RESULT
    assert messages[0].metadata == {"tool_call_id": "call_1", "is_error": True}

    assert messages[1].role == "tool"
    assert messages[1].content == _INTERRUPTED_TOOL_RESULT
    assert messages[1].metadata == {"tool_call_id": "call_2", "is_error": True}


# ─────────────────────────────────────────────────────────────
# 4. _execute_tools_turn Tests
# ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_execute_tools_turn_pi_timing_and_blocking():
    reg = ToolRegistry()

    @tool(description="echo")
    def echo(text: str) -> str:
        return f"echo: {text}"

    reg.register(echo)

    tool_calls = [
        {"id": "call_1", "function": {"name": "echo", "arguments": '{"text": "safe"}'}},
        {
            "id": "call_2",
            "function": {"name": "echo", "arguments": '{"text": "blocked"}'},
        },
    ]

    async def guard(decision: ToolCallHook):
        if decision.args.get("text") == "blocked":
            return HookResult(block=True, reason="policy violation")
        return None

    events = []
    async for ev in _execute_tools_turn(
        tool_calls=tool_calls,
        registry=reg,
        before_tool_call=guard,
        after_tool_call=None,
        signal=None,
    ):
        events.append(ev)

    # 1. Preflight starts emitted in source order first
    starts = [e for e in events if isinstance(e, ToolExecutionStart)]
    assert len(starts) == 2
    assert starts[0].tool_call_id == "call_1"
    assert starts[1].tool_call_id == "call_2"

    # 2. Ends emitted
    ends = [e for e in events if isinstance(e, ToolExecutionEnd)]
    assert len(ends) == 2
    assert ends[0].tool_call_id == "call_1" and not ends[0].is_error
    assert ends[1].tool_call_id == "call_2" and ends[1].is_error
    assert "blocked: policy violation" in ends[1].result

    # 3. MessageStart and MessageEnd yielded in source order
    tool_ends = [
        e for e in events if isinstance(e, MessageEnd) and e.message.role == "tool"
    ]
    assert len(tool_ends) == 2
    assert tool_ends[0].message.metadata is not None
    assert tool_ends[1].message.metadata is not None
    assert tool_ends[0].message.metadata["tool_call_id"] == "call_1"
    assert tool_ends[1].message.metadata["tool_call_id"] == "call_2"


@pytest.mark.anyio
async def test_execute_tools_turn_preflight_timing_invariant():
    """Verify that all ToolExecutionStart events are emitted before any before_tool_call runs."""
    reg = ToolRegistry()

    @tool(description="calc")
    def calc(n: int) -> int:
        return n * 2

    reg.register(calc)

    tool_calls = [
        {"id": "c1", "function": {"name": "calc", "arguments": '{"n": 1}'}},
        {"id": "c2", "function": {"name": "calc", "arguments": '{"n": 2}'}},
    ]

    events_order = []

    async def track_guard(_decision: ToolCallHook):
        # When guard runs for ANY tool call, all ToolExecutionStart events MUST have already been emitted
        current_starts = [e for e in events_order if isinstance(e, ToolExecutionStart)]
        assert len(current_starts) == 2
        return None

    async for ev in _execute_tools_turn(
        tool_calls=tool_calls,
        registry=reg,
        before_tool_call=track_guard,
        after_tool_call=None,
        signal=None,
    ):
        events_order.append(ev)

    starts = [e for e in events_order if isinstance(e, ToolExecutionStart)]
    assert len(starts) == 2


@pytest.mark.anyio
async def test_execute_tools_turn_args_and_result_rewriting():
    reg = ToolRegistry()

    @tool(description="greet")
    def greet(name: str) -> str:
        return f"hello {name}"

    reg.register(greet)

    tool_calls = [
        {
            "id": "call_1",
            "function": {"name": "greet", "arguments": '{"name": "Alice"}'},
        },
    ]

    async def rewrite_args(_decision: ToolCallHook):
        return HookResult(updated_args={"name": "Bob"})

    async def rewrite_result(decision: ToolResultHook):
        assert decision.result == "hello Bob"
        return HookResult(updated_result="welcome Bob")

    events = []
    async for ev in _execute_tools_turn(
        tool_calls=tool_calls,
        registry=reg,
        before_tool_call=rewrite_args,
        after_tool_call=rewrite_result,
        signal=None,
    ):
        events.append(ev)

    end_ev = [e for e in events if isinstance(e, ToolExecutionEnd)][0]
    assert end_ev.result == "welcome Bob"
    assert not end_ev.is_error

    msg_ev = [
        e for e in events if isinstance(e, MessageEnd) and e.message.role == "tool"
    ][0]
    assert msg_ev.message.content == "welcome Bob"


@pytest.mark.anyio
async def test_execute_tools_turn_cancellation_synthesizes_interrupted():
    reg = ToolRegistry()

    @tool(description="ping")
    def ping() -> str:
        return "pong"

    reg.register(ping)

    token = CancellationToken()
    token.cancel()  # Cancelled before tool execution

    tool_calls = [
        {"id": "call_1", "function": {"name": "ping", "arguments": "{}"}},
    ]

    events = []
    async for ev in _execute_tools_turn(
        tool_calls=tool_calls,
        registry=reg,
        before_tool_call=None,
        after_tool_call=None,
        signal=token,
    ):
        events.append(ev)

    end_ev = [e for e in events if isinstance(e, ToolExecutionEnd)][0]
    assert end_ev.is_error
    assert end_ev.result == _INTERRUPTED_TOOL_RESULT

    msg_ev = [
        e for e in events if isinstance(e, MessageEnd) and e.message.role == "tool"
    ][0]
    assert msg_ev.message.content == _INTERRUPTED_TOOL_RESULT
    assert msg_ev.message.metadata is not None
    assert msg_ev.message.metadata["is_error"]


@pytest.mark.anyio
async def test_execute_tools_turn_invalid_json_args():
    reg = ToolRegistry()

    @tool(description="ping")
    def ping() -> str:
        return "pong"

    reg.register(ping)

    tool_calls = [
        {"id": "call_bad", "function": {"name": "ping", "arguments": "invalid-json{"}},
    ]

    events = []
    async for ev in _execute_tools_turn(
        tool_calls=tool_calls,
        registry=reg,
        before_tool_call=None,
        after_tool_call=None,
        signal=None,
    ):
        events.append(ev)

    # ToolExecutionStart was emitted with args={}
    start_ev = [e for e in events if isinstance(e, ToolExecutionStart)][0]
    assert start_ev.args == {}

    # ToolExecutionEnd was emitted with is_error=True
    end_ev = [e for e in events if isinstance(e, ToolExecutionEnd)][0]
    assert end_ev.is_error
    assert "Invalid JSON arguments" in end_ev.result
