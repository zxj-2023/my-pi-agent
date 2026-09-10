"""events.py 纯只读事件与五大决策拦截点离线单测。

验证：
1. Event 及其所有子类均为纯粹不可变 (frozen) dataclass，携带只读 timestamp。
2. 彻底移除 Interceptable 标记类，所有 Event 子类均无 Interceptable 继承痕迹。
3. 五大专职 Decision 决策点均为独立不可变 dataclass，携带指定强类型属性。
4. TurnEnd 支持可空 message 及默认空列表 tool_results。
5. DecisionRegistry（及 HookRegistry 别名）支持注册、注销、async/sync 混合调用、首个非 None 短路，以及 Never-Throw 异常捕获隔离。
"""

import asyncio
from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest
from my_agent_llm import Message, StreamChunk

import my_agent_core.events as events_module
from my_agent_core.events import (
    AgentEnd,
    AgentEvent,
    AgentStart,
    AgentStartDecision,
    BeforeModelCallDecision,
    ContextCompacted,
    DecisionRegistry,
    Event,
    HookRegistry,
    HookResult,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolCallDecision,
    ToolExecutionEnd,
    ToolExecutionStart,
    ToolExecutionUpdate,
    ToolResultDecision,
    ToolsChanged,
    TurnEnd,
    TurnStart,
    UserInputDecision,
)


def test_interceptable_does_not_exist():
    """Interceptable 标记类彻底移除，不存在于 events 模块中。"""
    assert not hasattr(events_module, "Interceptable")


def test_events_are_pure_frozen_dataclasses():
    """Event 及其所有子类是纯粹 frozen dataclass，不可变且携带 timestamp。"""
    ev = TurnStart(iteration=1)
    assert isinstance(ev, Event)
    assert hasattr(ev, "timestamp")
    assert isinstance(ev.timestamp, float)
    with pytest.raises(FrozenInstanceError):
        ev.iteration = 2  # pyright: ignore[reportAttributeAccessIssue]


def test_all_event_subclasses_frozen_with_timestamp():
    """所有规范定义的事件均继承 Event、是 frozen dataclass 且包含 timestamp。"""
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
        assert "timestamp" in [f.name for f in fields(cls)]


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


def test_agent_event_alias():
    """AgentEvent 是 Event 的类型别名。"""
    assert AgentEvent is Event


def test_decision_points_attributes_and_frozen():
    """五大专职 Decision 决策点包含预期字段且为不可变 frozen dataclass，不继承 Event。"""
    uid = UserInputDecision(input_text="hello")
    assert uid.input_text == "hello"
    assert is_dataclass(uid) and uid.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(uid, Event)
    with pytest.raises(FrozenInstanceError):
        uid.input_text = "mutated"  # pyright: ignore[reportAttributeAccessIssue]

    asd = AgentStartDecision(system_prompt="you are a helpful assistant")
    assert asd.system_prompt == "you are a helpful assistant"
    assert is_dataclass(asd) and asd.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(asd, Event)

    msg = Message(role="user", content="ping")
    bmcd = BeforeModelCallDecision(messages=[msg], iteration=2)
    assert bmcd.messages == [msg]
    assert bmcd.iteration == 2
    assert is_dataclass(bmcd) and bmcd.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(bmcd, Event)

    tcd = ToolCallDecision(tool_call_id="call_1", tool_name="bash", args={"cmd": "ls"})
    assert tcd.tool_call_id == "call_1"
    assert tcd.tool_name == "bash"
    assert tcd.args == {"cmd": "ls"}
    assert is_dataclass(tcd) and tcd.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(tcd, Event)

    trd = ToolResultDecision(
        tool_call_id="call_1", tool_name="bash", result="output", is_error=False
    )
    assert trd.tool_call_id == "call_1"
    assert trd.tool_name == "bash"
    assert trd.result == "output"
    assert trd.is_error is False
    assert is_dataclass(trd) and trd.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(trd, Event)


def test_hook_result_fields_and_defaults():
    """HookResult 包含拦截/改写所需字段且默认为无干预。"""
    hr = HookResult()
    assert hr.block is False
    assert hr.reason is None
    assert hr.updated_input is None
    assert hr.updated_system_prompt is None
    assert hr.updated_messages is None
    assert hr.updated_args is None
    assert hr.updated_result is None

    msg = Message(role="system", content="updated")
    hr_custom = HookResult(
        block=True,
        reason="blocked",
        updated_input="new_input",
        updated_system_prompt="new_prompt",
        updated_messages=[msg],
        updated_args={"x": 1},
        updated_result="new_res",
    )
    assert hr_custom.block is True
    assert hr_custom.reason == "blocked"
    assert hr_custom.updated_input == "new_input"
    assert hr_custom.updated_system_prompt == "new_prompt"
    assert hr_custom.updated_messages == [msg]
    assert hr_custom.updated_args == {"x": 1}
    assert hr_custom.updated_result == "new_res"


def test_hook_registry_alias():
    """HookRegistry 是 DecisionRegistry 的别名。"""
    assert HookRegistry is DecisionRegistry


@pytest.mark.anyio
async def test_decision_registry_emit_and_short_circuit():
    """DecisionRegistry 执行 handlers，遇到第一个非 None HookResult 立即短路并返回。"""
    reg = DecisionRegistry()
    calls = []

    async def guard(d: ToolCallDecision):
        calls.append(d.tool_name)
        return HookResult(block=True, reason="forbidden")

    async def second_guard(_d: ToolCallDecision):
        calls.append("should_not_run")
        return None

    reg.register(ToolCallDecision, guard)
    reg.register(ToolCallDecision, second_guard)

    res = await reg.emit(ToolCallDecision(tool_call_id="1", tool_name="rm", args={}))
    assert res is not None
    assert res.block is True
    assert res.reason == "forbidden"
    assert calls == ["rm"]


@pytest.mark.anyio
async def test_decision_registry_sync_and_async_mix():
    """DecisionRegistry 支持 sync 与 async 回调混用，全部返回 None 则 emit 返回 None。"""
    reg = DecisionRegistry()
    calls = []

    def sync_observer(d: UserInputDecision):
        calls.append(f"sync:{d.input_text}")
        return None

    async def async_observer(d: UserInputDecision):
        await asyncio.sleep(0.001)
        calls.append(f"async:{d.input_text}")
        return None

    reg.register(UserInputDecision, sync_observer)
    reg.register(UserInputDecision, async_observer)

    res = await reg.emit(UserInputDecision(input_text="hello"))
    assert res is None
    assert calls == ["sync:hello", "async:hello"]


@pytest.mark.anyio
async def test_decision_registry_unregister():
    """DecisionRegistry.unregister 正常移除已注册回调。"""
    reg = DecisionRegistry()
    calls = []

    def hook(_d: AgentStartDecision):
        calls.append("called")
        return HookResult(block=True)

    reg.register(AgentStartDecision, hook)
    reg.unregister(AgentStartDecision, hook)

    res = await reg.emit(AgentStartDecision(system_prompt="sys"))
    assert res is None
    assert calls == []


@pytest.mark.anyio
async def test_decision_registry_never_throw_guarantee():
    """DecisionRegistry 严格保证 Never-Throw：回调抛出异常时不向外抛，捕获后继续执行后续回调。"""
    reg = DecisionRegistry()
    calls = []

    def crashing_sync_hook(_d: ToolCallDecision):
        calls.append("crashing_sync")
        raise RuntimeError("boom in sync hook")

    async def crashing_async_hook(_d: ToolCallDecision):
        calls.append("crashing_async")
        raise ValueError("boom in async hook")

    async def successful_hook(_d: ToolCallDecision):
        calls.append("successful")
        return HookResult(block=True, reason="blocked after errors")

    reg.register(ToolCallDecision, crashing_sync_hook)
    reg.register(ToolCallDecision, crashing_async_hook)
    reg.register(ToolCallDecision, successful_hook)

    # 绝不能抛出异常
    res = await reg.emit(
        ToolCallDecision(tool_call_id="call_x", tool_name="bash", args={})
    )
    assert res is not None
    assert res.block is True
    assert res.reason == "blocked after errors"
    assert calls == ["crashing_sync", "crashing_async", "successful"]


@pytest.mark.anyio
async def test_decision_registry_never_throw_all_fail():
    """当所有回调均抛异常时，DecisionRegistry.emit 返回 None 且不抛出异常。"""
    reg = DecisionRegistry()

    def crashing_hook(_d: ToolResultDecision):
        raise KeyError("missing key")

    reg.register(ToolResultDecision, crashing_hook)

    res = await reg.emit(
        ToolResultDecision(
            tool_call_id="1", tool_name="bash", result="err", is_error=True
        )
    )
    assert res is None
