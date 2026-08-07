"""events.py 事件 dataclass + emit 离线测试：可导入、可实例化、字段正确、转发正确。"""
from dataclasses import fields, is_dataclass

import pytest

from my_agent_llm import Message

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    ContextCompacted,
    Event,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    ToolExecutionUpdate,
    ToolsChanged,
    TurnEnd,
    TurnStart,
    emit,
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
    e = ToolExecutionStart(tool_call_id="1", tool_name="multiply", args={"a": 2, "b": 3})
    assert (e.tool_call_id, e.tool_name, e.args) == ("1", "multiply", {"a": 2, "b": 3})


def test_tool_execution_update_fields():
    """ToolExecutionUpdate 带 partial_result。"""
    e = ToolExecutionUpdate(tool_call_id="1", tool_name="multiply", args={}, partial_result="2")
    assert e.partial_result == "2"


def test_tool_execution_end_fields():
    """ToolExecutionEnd 带 tool_call_id/tool_name/result/is_error。"""
    e = ToolExecutionEnd(tool_call_id="1", tool_name="multiply", result="6", is_error=False)
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
    """全部事件都是 frozen dataclass，非空 fields（AgentStart 无字段跳过）。"""
    with_fields = (TurnStart, TurnEnd, MessageStart, MessageUpdate, MessageEnd,
                   ToolExecutionStart, ToolExecutionUpdate, ToolExecutionEnd,
                   AgentEnd, ContextCompacted, ToolsChanged)
    no_fields = (AgentStart,)
    for cls in (*with_fields, *no_fields):
        assert is_dataclass(cls)
        assert cls.__dataclass_params__.frozen
    for cls in with_fields:
        assert fields(cls)


def test_emit_forwards_to_callback():
    """emit 把事件转发给回调。"""
    received = []
    emit(received.append, TurnStart(iteration=1))
    assert received == [TurnStart(iteration=1)]


def test_emit_none_callback_is_noop():
    """on_event 为 None 时 emit 为空操作（不抛）。"""
    emit(None, AgentStart())  # 不抛即通过


def test_emit_callback_exception_propagates():
    """回调抛异常直接向上传播（on_event 异常不兜底，视为使用方 bug）。"""
    def boom(event):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        emit(boom, AgentStart())


def test_event_has_timestamp():
    """每个事件实例自动带 timestamp（Unix 秒，接近当前时间）。"""
    import time

    before = time.time()
    e = TurnStart(iteration=1)
    after = time.time()
    assert before <= e.timestamp <= after


def test_all_events_have_timestamp():
    """全部事件实例都有 timestamp（继承自 Event 基类）。"""
    def make(cls):
        if cls is AgentStart:
            return cls()
        if cls is TurnStart:
            return cls(iteration=1)
        if cls in (MessageStart, MessageEnd):
            return cls(message=Message(role="assistant", content="hi"))
        if cls is ToolExecutionStart:
            return cls(tool_call_id="1", tool_name="f", args={})
        if cls is ToolExecutionEnd:
            return cls(tool_call_id="1", tool_name="f", result="", is_error=False)
        if cls is AgentEnd:
            return cls(messages=[], final_text=None, iterations=1, stop_reason="end_turn")
        if cls is ContextCompacted:
            return cls(tokens_before=1, tokens_after=1, summarized_count=0)
        if cls is ToolsChanged:
            return cls(action="registered", name="x")
        raise AssertionError(f"no constructor for {cls.__name__}")

    for cls in (AgentStart, TurnStart, MessageStart, MessageEnd,
                ToolExecutionStart, ToolExecutionEnd, AgentEnd,
                ContextCompacted, ToolsChanged):
        e = make(cls)
        assert hasattr(e, "timestamp")
        assert isinstance(e.timestamp, float)
