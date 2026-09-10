"""events.py 纯只读事件与五大 Hook 拦截点离线单测。

验证：
1. Event 及其所有子类均为纯粹不可变 (frozen) dataclass，携带只读 timestamp。
2. 彻底移除 Interceptable 标记类与 Decision 生造类，所有 Event 子类均无 Interceptable 继承痕迹。
3. 五大专职 Hook 拦截点均为独立不可变 dataclass，携带指定强类型属性。
4. TurnEnd 支持可空 message 及默认空列表 tool_results。
5. HookRegistry 支持注册、注销、async/sync 混合调用、首个非 None 短路，以及 Never-Throw 异常捕获隔离。
"""

import asyncio
from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest
from my_agent_llm import Message, StreamChunk

import my_agent_core.events as events_module
from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    AgentStartHook,
    BeforeModelCallHook,
    ContextCompacted,
    Event,
    HookRegistry,
    HookResult,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolCallHook,
    ToolExecutionEnd,
    ToolExecutionStart,
    ToolExecutionUpdate,
    ToolResultHook,
    ToolsChanged,
    TurnEnd,
    TurnStart,
    UserInputHook,
)


def test_interceptable_and_decision_do_not_exist():
    """验证架构彻底解耦：Interceptable、Decision 生造类及混乱别名完全不存在。"""
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

    # 顶层包导出中也彻底消除
    import my_agent_core

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


def test_hook_points_attributes_and_frozen():
    """五大专职 Hook 拦截点包含预期字段且为不可变 frozen dataclass，不继承 Event。"""
    uid = UserInputHook(input_text="hello")
    assert uid.input_text == "hello"
    assert is_dataclass(uid) and uid.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(uid, Event)
    with pytest.raises(FrozenInstanceError):
        uid.input_text = "mutated"  # pyright: ignore[reportAttributeAccessIssue]

    ash = AgentStartHook(system_prompt="you are a helpful assistant")
    assert ash.system_prompt == "you are a helpful assistant"
    assert is_dataclass(ash) and ash.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(ash, Event)

    msg = Message(role="user", content="ping")
    bmch = BeforeModelCallHook(messages=[msg], iteration=2)
    assert bmch.messages == [msg]
    assert bmch.iteration == 2
    assert is_dataclass(bmch) and bmch.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(bmch, Event)

    tch = ToolCallHook(tool_call_id="call_1", tool_name="bash", args={"cmd": "ls"})
    assert tch.tool_call_id == "call_1"
    assert tch.tool_name == "bash"
    assert tch.args == {"cmd": "ls"}
    assert is_dataclass(tch) and tch.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(tch, Event)

    trh = ToolResultHook(
        tool_call_id="call_1", tool_name="bash", result="output", is_error=False
    )
    assert trh.tool_call_id == "call_1"
    assert trh.tool_name == "bash"
    assert trh.result == "output"
    assert trh.is_error is False
    assert is_dataclass(trh) and trh.__dataclass_params__.frozen  # pyright: ignore[reportAttributeAccessIssue]
    assert not isinstance(trh, Event)


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


@pytest.mark.anyio
async def test_hook_registry_emit_and_short_circuit():
    """HookRegistry 执行 handlers，遇到第一个非 None HookResult 立即短路并返回。"""
    reg = HookRegistry()
    calls = []

    async def guard(d: ToolCallHook):
        calls.append(d.tool_name)
        return HookResult(block=True, reason="forbidden")

    async def second_guard(_d: ToolCallHook):
        calls.append("should_not_run")
        return None

    reg.register(ToolCallHook, guard)
    reg.register(ToolCallHook, second_guard)

    res = await reg.emit(ToolCallHook(tool_call_id="1", tool_name="rm", args={}))
    assert res is not None
    assert res.block is True
    assert res.reason == "forbidden"
    assert calls == ["rm"]


@pytest.mark.anyio
async def test_hook_registry_sync_and_async_mix():
    """HookRegistry 支持 sync 与 async 回调混用，全部返回 None 则 emit 返回 None。"""
    reg = HookRegistry()
    calls = []

    def sync_observer(d: UserInputHook):
        calls.append(f"sync:{d.input_text}")
        return None

    async def async_observer(d: UserInputHook):
        await asyncio.sleep(0.001)
        calls.append(f"async:{d.input_text}")
        return None

    reg.register(UserInputHook, sync_observer)
    reg.register(UserInputHook, async_observer)

    res = await reg.emit(UserInputHook(input_text="hello"))
    assert res is None
    assert calls == ["sync:hello", "async:hello"]


@pytest.mark.anyio
async def test_hook_registry_unregister():
    """HookRegistry.unregister 正常移除已注册回调。"""
    reg = HookRegistry()
    calls = []

    def hook(_d: AgentStartHook):
        calls.append("called")
        return HookResult(block=True)

    reg.register(AgentStartHook, hook)
    reg.unregister(AgentStartHook, hook)

    res = await reg.emit(AgentStartHook(system_prompt="sys"))
    assert res is None
    assert calls == []


@pytest.mark.anyio
async def test_hook_registry_never_throw_guarantee():
    """HookRegistry 严格保证 Never-Throw：回调抛出异常时不向外抛，捕获后继续执行后续回调。"""
    reg = HookRegistry()
    calls = []

    def crashing_sync_hook(_d: ToolCallHook):
        calls.append("crashing_sync")
        raise RuntimeError("boom in sync hook")

    async def crashing_async_hook(_d: ToolCallHook):
        calls.append("crashing_async")
        raise ValueError("boom in async hook")

    async def successful_hook(_d: ToolCallHook):
        calls.append("successful")
        return HookResult(block=True, reason="blocked after errors")

    reg.register(ToolCallHook, crashing_sync_hook)
    reg.register(ToolCallHook, crashing_async_hook)
    reg.register(ToolCallHook, successful_hook)

    # 绝不能抛出异常
    res = await reg.emit(ToolCallHook(tool_call_id="call_x", tool_name="bash", args={}))
    assert res is not None
    assert res.block is True
    assert res.reason == "blocked after errors"
    assert calls == ["crashing_sync", "crashing_async", "successful"]


@pytest.mark.anyio
async def test_hook_registry_never_throw_all_fail():
    """当所有回调均抛异常时，HookRegistry.emit 返回 None 且不抛出异常。"""
    reg = HookRegistry()

    def crashing_hook(_d: ToolResultHook):
        raise KeyError("missing key")

    reg.register(ToolResultHook, crashing_hook)

    res = await reg.emit(
        ToolResultHook(tool_call_id="1", tool_name="bash", result="err", is_error=True)
    )
    assert res is None
