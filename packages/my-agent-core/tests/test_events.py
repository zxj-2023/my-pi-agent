"""events.py 事件 dataclass + HookResult 离线测试：可导入、可实例化、字段正确。"""

import asyncio
from dataclasses import fields, is_dataclass

import pytest
from my_agent_llm import Message, StreamChunk

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    BeforeModelCall,
    ContextCompacted,
    Event,
    HookRegistry,
    HookResult,
    Interceptable,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    ToolExecutionUpdate,
    ToolsChanged,
    TurnEnd,
    TurnStart,
    UserInput,
)


def test_event_is_dataclass_base():
    """Event 基类是 dataclass（供 Callable[[Event], None] 类型标注）。"""
    assert is_dataclass(Event)


def test_agent_start_instantiates():
    """AgentStart 可实例化（无字段）。"""
    assert AgentStart()


def test_turn_start_has_iteration():
    """TurnStart 带 iteration 字段。"""
    e = TurnStart(iteration=1)
    assert e.iteration == 1


def test_turn_end_fields():
    """TurnEnd 带 message/tool_results。"""
    m = Message(role="assistant", content="hi")
    t = Message(role="tool", content="6")
    e = TurnEnd(message=m, tool_results=[t])
    assert e.message is m
    assert e.tool_results == [t]


def test_message_lifecycle_events_carry_message():
    """MessageStart/MessageUpdate/MessageEnd 带 Message 对象。"""
    m = Message(role="assistant", content="hi")
    assert MessageStart(message=m).message is m
    assert MessageUpdate(message=m).message is m
    assert MessageEnd(message=m).message is m


def test_tool_execution_start_fields():
    """ToolExecutionStart 带 tool_call_id/tool_name/args。"""
    e = ToolExecutionStart(
        tool_call_id="1", tool_name="multiply", args={"a": 2, "b": 3}
    )
    assert (e.tool_call_id, e.tool_name, e.args) == ("1", "multiply", {"a": 2, "b": 3})


def test_tool_execution_update_fields():
    """ToolExecutionUpdate 带 partial_result。"""
    e = ToolExecutionUpdate(
        tool_call_id="1", tool_name="multiply", args={}, partial_result="2"
    )
    assert e.partial_result == "2"


def test_tool_execution_end_fields():
    """ToolExecutionEnd 带 tool_call_id/tool_name/result/is_error。"""
    e = ToolExecutionEnd(
        tool_call_id="1", tool_name="multiply", result="6", is_error=False
    )
    assert e.result == "6"
    assert e.is_error is False


def test_agent_end_fields():
    """AgentEnd 带 messages/final_text/iterations/stop_reason。"""
    m = Message(role="assistant", content="hi")
    e = AgentEnd(messages=[m], final_text="hi", iterations=2, stop_reason="end_turn")
    assert e.messages == [m]
    assert (e.final_text, e.iterations, e.stop_reason) == ("hi", 2, "end_turn")


def test_context_compacted_fields():
    """ContextCompacted 带 tokens_before/tokens_after/summarized_count。"""
    e = ContextCompacted(tokens_before=100, tokens_after=50, summarized_count=3)
    assert e.tokens_after == 50


def test_tools_changed_fields():
    """ToolsChanged 带 action/name。"""
    e = ToolsChanged(action="registered", name="get_weather")
    assert e.name == "get_weather"


def test_all_events_frozen_and_dataclass():
    """全部事件都是 frozen dataclass，非空 fields。"""
    all_events = (
        UserInput,
        AgentStart,
        TurnStart,
        BeforeModelCall,
        TurnEnd,
        MessageStart,
        MessageUpdate,
        MessageEnd,
        ToolExecutionStart,
        ToolExecutionUpdate,
        ToolExecutionEnd,
        AgentEnd,
        ContextCompacted,
        ToolsChanged,
    )
    for cls in all_events:
        assert is_dataclass(cls)
        assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]
        assert fields(cls)


def test_event_has_timestamp():
    """每个事件实例自动带 timestamp（Unix 秒，接近当前时间）。"""
    import time

    before = time.time()
    e = TurnStart(iteration=1)
    after = time.time()
    assert before <= e.timestamp <= after  # type: ignore[attr-defined]


def test_all_events_have_timestamp():
    """全部事件实例都有 timestamp（继承自 Event 基类）。"""

    def make(cls):
        if cls is UserInput:
            return cls(input_text="hi")
        if cls is AgentStart:
            return cls()
        if cls is TurnStart:
            return cls(iteration=1)
        if cls is BeforeModelCall:
            return cls(messages=[], iteration=1)
        if cls in (MessageStart, MessageEnd):
            return cls(message=Message(role="assistant", content="hi"))
        if cls is ToolExecutionStart:
            return cls(tool_call_id="1", tool_name="f", args={})
        if cls is ToolExecutionEnd:
            return cls(tool_call_id="1", tool_name="f", result="", is_error=False)
        if cls is AgentEnd:
            return cls(
                messages=[], final_text=None, iterations=1, stop_reason="end_turn"
            )
        if cls is ContextCompacted:
            return cls(tokens_before=1, tokens_after=1, summarized_count=0)
        if cls is ToolsChanged:
            return cls(action="registered", name="x")
        raise AssertionError(f"no constructor for {cls.__name__}")

    for cls in (
        UserInput,
        AgentStart,
        TurnStart,
        BeforeModelCall,
        MessageStart,
        MessageEnd,
        ToolExecutionStart,
        ToolExecutionEnd,
        AgentEnd,
        ContextCompacted,
        ToolsChanged,
    ):
        e = make(cls)
        assert hasattr(e, "timestamp")
        assert isinstance(e.timestamp, float)  # type: ignore[attr-defined]


def test_hook_result_fields():
    """HookResult 四字段，默认值正确。"""
    r = HookResult()
    assert r.block is False
    assert r.reason is None
    assert r.updated_args is None
    assert r.updated_result is None
    r2 = HookResult(
        block=True, reason="denied", updated_args={"a": 1}, updated_result="hi"
    )
    assert r2.block is True
    assert r2.reason == "denied"
    assert r2.updated_args == {"a": 1}
    assert r2.updated_result == "hi"


def test_interceptable_events():
    """ToolExecutionStart/End、MessageUpdate、UserInput、AgentStart、BeforeModelCall 继承 Interceptable。"""
    assert isinstance(
        ToolExecutionStart(tool_call_id="1", tool_name="f", args={}), Interceptable
    )
    assert isinstance(
        ToolExecutionEnd(tool_call_id="1", tool_name="f", result="", is_error=False),
        Interceptable,
    )
    assert isinstance(
        MessageUpdate(message=Message(role="assistant", content="hi")), Interceptable
    )
    assert isinstance(UserInput(input_text="hello"), Interceptable)
    assert isinstance(AgentStart(), Interceptable)
    assert isinstance(BeforeModelCall(messages=[], iteration=1), Interceptable)
    assert not isinstance(TurnStart(iteration=1), Interceptable)
    assert not isinstance(
        AgentEnd(messages=[], final_text=None, iterations=1, stop_reason="end_turn"),
        Interceptable,
    )


def test_extension_decision_point_events():
    """测试五大决策点相关的事件与 HookResult 扩充字段。"""
    # 1. UserInput
    e_input = UserInput(input_text="hello world")
    assert isinstance(e_input, Interceptable)
    assert e_input.input_text == "hello world"

    # 2. AgentStart (Interceptable with system_prompt & user_input)
    e_start = AgentStart(system_prompt="system prompt", user_input="user prompt")
    assert isinstance(e_start, Interceptable)
    assert e_start.system_prompt == "system prompt"
    assert e_start.user_input == "user prompt"

    # 3. BeforeModelCall
    msg = Message(role="user", content="hi")
    e_ctx = BeforeModelCall(messages=[msg], iteration=1)
    assert isinstance(e_ctx, Interceptable)
    assert e_ctx.messages == [msg]
    assert e_ctx.iteration == 1

    # 4. HookResult 扩充字段
    res = HookResult(
        block=True,
        reason="blocked",
        updated_input="new input",
        updated_system_prompt="new system",
        updated_messages=[msg],
        updated_args={"a": 1},
        updated_result="res",
    )
    assert res.updated_input == "new input"
    assert res.updated_system_prompt == "new system"
    assert res.updated_messages == [msg]


def test_hook_result_frozen():
    """HookResult 是 frozen dataclass。"""
    assert is_dataclass(HookResult)
    assert HookResult.__dataclass_params__.frozen  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_hook_registry_async_emit():
    """HookRegistry.emit 支持异步与同步 hook 混用，并正确短路。"""
    registry = HookRegistry()
    calls = []

    async def async_hook(event: Event):
        await asyncio.sleep(0.01)
        calls.append("async")
        return None

    def sync_hook(event: Event):
        calls.append("sync")
        return HookResult(block=True, reason="blocked in sync")

    def never_called(event: Event):
        calls.append("never")
        return None

    registry.register(MessageUpdate, async_hook)
    registry.register(MessageUpdate, sync_hook)
    registry.register(MessageUpdate, never_called)

    msg = Message(role="assistant", content="hello")
    chunk = StreamChunk(content="lo")
    event = MessageUpdate(message=msg, chunk=chunk)

    assert issubclass(MessageUpdate, Interceptable)
    res = await registry.emit(event)

    assert calls == ["async", "sync"]
    assert res is not None
    assert res.block is True
    assert res.reason == "blocked in sync"
