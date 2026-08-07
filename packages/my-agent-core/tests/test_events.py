"""events.py 事件 dataclass + emit 离线测试：可导入、可实例化、字段正确、转发正确。"""
from dataclasses import fields, is_dataclass

import pytest

from my_agent_llm import Message

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    AssistantMessageAdded,
    ContextCompacted,
    Event,
    ToolCallEnd,
    ToolCallStart,
    ToolsChanged,
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


def test_assistant_message_added_carries_message():
    """AssistantMessageAdded.message 是 Message 对象（非 dict）。"""
    m = Message(role="assistant", content="hi")
    e = AssistantMessageAdded(message=m)
    assert e.message is m


def test_tool_call_start_fields():
    """ToolCallStart 带 call_id/name/args。"""
    e = ToolCallStart(call_id="1", name="multiply", args={"a": 2, "b": 3})
    assert (e.call_id, e.name, e.args) == ("1", "multiply", {"a": 2, "b": 3})


def test_tool_call_end_fields():
    """ToolCallEnd 带 call_id/name/result/is_error。"""
    e = ToolCallEnd(call_id="1", name="multiply", result="6", is_error=False)
    assert e.result == "6"
    assert e.is_error is False


def test_agent_end_fields():
    """AgentEnd 带 final_text/iterations/stop_reason。"""
    e = AgentEnd(final_text="hi", iterations=2, stop_reason="end_turn")
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
    """全部 8 个事件都是 frozen dataclass。"""
    for cls in (AgentStart, TurnStart, AssistantMessageAdded, ToolCallStart,
                ToolCallEnd, AgentEnd, ContextCompacted, ToolsChanged):
        assert is_dataclass(cls)
        assert cls.__dataclass_params__.frozen  # 全部 frozen
    for cls in (TurnStart, AssistantMessageAdded, ToolCallStart, ToolCallEnd,
                AgentEnd, ContextCompacted, ToolsChanged):
        assert fields(cls)  # 非空 dataclass（AgentStart 无字段，跳过）


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
