"""hooks.py 专职 Hook 拦截点与 HookRegistry 离线单测。

验证：
1. 五大专职 Hook 拦截点均为独立不可变 (frozen) dataclass，携带指定强类型属性，不继承 Event。
2. HookResult 包含完整的干预字段且默认值为不干预。
3. HookRegistry 支持注册、注销、async/sync 混合调用、首个非 None 短路，以及 Never-Throw 异常捕获隔离。
"""

import asyncio
from dataclasses import FrozenInstanceError, is_dataclass

import pytest
from my_agent_llm import Message

from my_agent_core.events import Event
from my_agent_core.hooks import (  # pyright: ignore[reportMissingImports]
    AgentStartHook,
    BeforeModelCallHook,
    HookRegistry,
    HookResult,
    ToolCallHook,
    ToolResultHook,
    UserInputHook,
)


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

    trh = ToolResultHook(tool_call_id="call_1", tool_name="bash", result="output", is_error=False)
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
    assert hr.terminate is None

    msg = Message(role="system", content="updated")
    hr_custom = HookResult(
        block=True,
        reason="blocked",
        updated_input="new_input",
        updated_system_prompt="new_prompt",
        updated_messages=[msg],
        updated_args={"x": 1},
        updated_result="new_res",
        terminate=True,
    )
    assert hr_custom.block is True
    assert hr_custom.reason == "blocked"
    assert hr_custom.updated_input == "new_input"
    assert hr_custom.updated_system_prompt == "new_prompt"
    assert hr_custom.updated_messages == [msg]
    assert hr_custom.updated_args == {"x": 1}
    assert hr_custom.updated_result == "new_res"
    assert hr_custom.terminate is True


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

    res = await reg.emit(ToolResultHook(tool_call_id="1", tool_name="bash", result="err", is_error=True))
    assert res is None
