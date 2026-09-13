"""events.py 纯只读事实事件离线单测。

验证：
1. Event 及其所有子类均为纯粹不可变 (frozen) dataclass，携带只读 timestamp。
2. 彻底解耦：events.py 中绝无任何 Hook 拦截契约或 HookRegistry（已正交下沉至 hooks.py）。
3. 彻底移除 Interceptable、Decision 生造类及混乱别名。
4. TurnEnd 支持可空 message 及默认空列表 tool_results。
"""

from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest
from my_agent_llm import Message, StreamChunk

import my_agent_core
import my_agent_core.events as events_module
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
)


def test_events_module_is_pure_readonly_facts():
    """验证 events.py 纯粹为只读事实通知，绝不包含 Hook、Decision、Interceptable 或别名。"""
    # 彻底解耦：Hook 相关的符号绝不出现于 events 模块
    assert not hasattr(events_module, "HookRegistry")
    assert not hasattr(events_module, "HookResult")
    assert not hasattr(events_module, "ToolCallHook")
    assert not hasattr(events_module, "ToolResultHook")
    assert not hasattr(events_module, "BeforeModelCallHook")
    assert not hasattr(events_module, "AgentStartHook")
    assert not hasattr(events_module, "UserInputHook")

    # 历史遗留与别名彻底清除
    assert not hasattr(events_module, "Interceptable")
    assert not hasattr(events_module, "DecisionRegistry")
    assert not hasattr(events_module, "ToolCallDecision")
    assert not hasattr(events_module, "ToolResultDecision")
    assert not hasattr(events_module, "BeforeModelCallDecision")
    assert not hasattr(events_module, "AgentStartDecision")
    assert not hasattr(events_module, "UserInputDecision")
    assert not hasattr(events_module, "AgentEvent")
    assert not hasattr(events_module, "UserInput")
    assert not hasattr(events_module, "BeforeModelCall")

    # 顶层包导出中也彻底消除了混乱别名
    assert not hasattr(my_agent_core, "Interceptable")
    assert not hasattr(my_agent_core, "DecisionRegistry")
    assert not hasattr(my_agent_core, "ToolCallDecision")
    assert not hasattr(my_agent_core, "ToolResultDecision")
    assert not hasattr(my_agent_core, "BeforeModelCallDecision")
    assert not hasattr(my_agent_core, "AgentStartDecision")
    assert not hasattr(my_agent_core, "UserInputDecision")
    assert not hasattr(my_agent_core, "AgentEvent")
    assert not hasattr(my_agent_core, "UserInput")
    assert not hasattr(my_agent_core, "BeforeModelCall")


def test_events_are_pure_frozen_dataclasses():
    """所有 Event 均为不可变 frozen dataclass，自动生成 timestamp 且不可篡改。"""
    ev = TurnStart(iteration=1)
    assert isinstance(ev, Event)
    assert hasattr(ev, "timestamp")
    assert isinstance(ev.timestamp, float)
    assert ev.iteration == 1

    # 验证不可变
    with pytest.raises(FrozenInstanceError):
        ev.iteration = 2  # pyright: ignore[reportAttributeAccessIssue]


def test_all_event_subclasses_frozen_with_timestamp():
    """全量覆盖 12 类 Event，验证它们都继承自 Event，带有只读 timestamp 且不可变。"""
    msg = Message(role="assistant", content="hello")
    all_event_instances: list[Event] = [
        AgentStart(system_prompt="sys", user_input="in"),
        AgentEnd(
            messages=[msg], final_text="bye", iterations=1, stop_reason="end_turn"
        ),
        TurnStart(iteration=1),
        TurnEnd(message=msg, tool_results=[]),
        MessageStart(message=msg),
        MessageUpdate(message=msg, chunk=StreamChunk(content="hi")),
        MessageEnd(message=msg),
        ToolExecutionStart(tool_call_id="call_1", tool_name="bash", args={"cmd": "ls"}),
        ToolExecutionUpdate(
            tool_call_id="call_1", tool_name="bash", args={}, partial_result="out"
        ),
        ToolExecutionEnd(
            tool_call_id="call_1", tool_name="bash", result="done", is_error=False
        ),
        ContextCompacted(tokens_before=100, tokens_after=50, summarized_count=2),
        ToolsChanged(action="register", name="bash"),
    ]

    for ev in all_event_instances:
        cls = type(ev)
        assert is_dataclass(cls), f"{cls.__name__} must be a dataclass"
        assert cls.__dataclass_params__.frozen, f"{cls.__name__} must be frozen"  # pyright: ignore[reportAttributeAccessIssue]
        assert isinstance(ev, Event), f"{cls.__name__} must inherit from Event"
        assert hasattr(ev, "timestamp"), f"{cls.__name__} must have timestamp"
        assert isinstance(ev.timestamp, float)
        # 确保 timestamp 暴露在 dataclass fields 中以供静态类型发现
        field_names = [f.name for f in fields(cls)]
        assert "timestamp" in field_names, f"timestamp not in {cls.__name__} fields"


def test_turn_end_nullable_message():
    """TurnEnd 支持 message=None 与 tool_results 默认空列表。"""
    te_none = TurnEnd(message=None, tool_results=[])
    assert te_none.message is None
    assert te_none.tool_results == []

    te_default = TurnEnd()
    assert te_default.message is None
    assert te_default.tool_results == []

    msg = Message(role="assistant", content="done")
    tool_msg = Message(role="tool", content="ok")
    te_populated = TurnEnd(message=msg, tool_results=[tool_msg])
    assert te_populated.message is msg
    assert te_populated.tool_results == [tool_msg]
