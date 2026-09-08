"""Unit tests for pure stateless ReAct microkernel (loop.py) and _provider_context.

Milestone 3 / Task 5 tests:
- _provider_context: cleans empty failure/aborted assistant messages and repairs tool history.
- CancellationToken: cooperative cancellation.
- run_agent_loop: pure async generator event stream, tool execution, steering, follow-up, cancellation, max_turns.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest
from my_agent_llm import Message, Response, StreamChunk

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    BeforeModelCall,
    HookRegistry,
    HookResult,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
)
from my_agent_core.loop import (
    CancellationToken,
    _provider_context,
    run_agent_loop,
)
from my_agent_core.registry import ToolRegistry
from my_agent_core.tools import tool

# ── Test Doubles ─────────────────────────────────────────────────────────────


class FakeLLM:
    """Async streaming FakeLLM for pure loop tests."""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def achat_stream(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        if not self.responses:
            yield StreamChunk(content="default reply", finish_reason="end_turn")
            return

        resp = self.responses.pop(0)
        if resp.content:
            mid = len(resp.content) // 2
            if mid > 0:
                yield StreamChunk(content=resp.content[:mid])
                yield StreamChunk(
                    content=resp.content[mid:],
                    tool_calls=resp.tool_calls,
                    finish_reason=resp.finish_reason,
                )
            else:
                yield StreamChunk(
                    content=resp.content,
                    tool_calls=resp.tool_calls,
                    finish_reason=resp.finish_reason,
                )
        elif resp.tool_calls:
            yield StreamChunk(content="", tool_calls=resp.tool_calls)
        else:
            yield StreamChunk(content="", finish_reason="end_turn")


@tool(is_parallel_safe=True)
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool(is_parallel_safe=True)
def ping() -> str:
    """Ping tool."""
    return "pong"


def _response(content: str = "", tool_calls=None) -> Response:
    return Response(content=content, model="fake", tool_calls=tool_calls)


def _make_registry(*tools) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ── _provider_context Tests ──────────────────────────────────────────────────


def test_provider_context_filters_empty_error_aborted_assistant():
    """验证 _provider_context 剔除 content 为空且 stop_reason in {'error', 'aborted'} 的助手消息。"""
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="query 1"),
        # 空且 error: 必须过滤
        Message(role="assistant", content="", metadata={"stop_reason": "error"}),
        # 空且 aborted: 必须过滤
        Message(role="assistant", content="", metadata={"stop_reason": "aborted"}),
        # 有正文且 error: 必须保留
        Message(
            role="assistant",
            content="partial error note",
            metadata={"stop_reason": "error"},
        ),
        # 空且 end_turn: 必须保留（正常无输出）
        Message(role="assistant", content="", metadata={"stop_reason": "end_turn"}),
        # 用户空消息: 必须保留
        Message(role="user", content=""),
    ]

    cleaned = _provider_context(messages)
    contents = [m.content for m in cleaned]
    roles = [m.role for m in cleaned]

    assert contents == ["sys", "query 1", "partial error note", "", ""]
    assert roles == ["system", "user", "assistant", "assistant", "user"]


def test_provider_context_repairs_tool_history():
    """验证 _provider_context 串联 repair_tool_history，补齐断头工具结果并丢弃孤儿结果。"""
    tc = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "ping", "arguments": "{}"},
        }
    ]
    messages = [
        Message(role="user", content="run ping"),
        Message(role="assistant", content="", metadata={"tool_calls": tc}),
        # 缺失 tool_call_id="call_1" 的结果，直接跟了一条孤儿结果 call_999
        Message(role="tool", content="orphan", metadata={"tool_call_id": "call_999"}),
    ]

    cleaned = _provider_context(messages)

    # 1. 孤儿结果 call_999 应被丢弃
    # 2. call_1 应被合成中断结果补齐
    assert len(cleaned) == 3
    assert cleaned[0].role == "user"
    assert cleaned[1].role == "assistant"
    assert cleaned[2].role == "tool"
    assert cleaned[2].metadata is not None
    assert cleaned[2].metadata["tool_call_id"] == "call_1"
    assert cleaned[2].metadata["is_error"] is True


# ── CancellationToken Tests ──────────────────────────────────────────────────


def test_cancellation_token_lifecycle():
    """验证 CancellationToken 的取消状态流转。"""
    token = CancellationToken()
    assert not token.is_cancelled()
    token.cancel()
    assert token.is_cancelled()


# ── run_agent_loop Tests ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_run_agent_loop_basic_lifecycle():
    """验证 run_agent_loop 独立运行产生的生命周期事件序列：
    AgentStart -> MessageStart/End -> TurnStart -> BeforeModelCall -> MessageUpdate -> TurnEnd -> AgentEnd。
    """
    llm = FakeLLM([_response(content="Hello world")])
    messages: list[Message] = []
    prompts = [Message(role="user", content="Hi")]

    events = []
    async for ev in run_agent_loop(
        llm=llm,
        messages=messages,
        prompts=prompts,
        system="You are helpful",
    ):
        events.append(ev)

    event_types = [type(e) for e in events]
    assert AgentStart in event_types
    assert TurnStart in event_types
    assert BeforeModelCall in event_types
    assert MessageUpdate in event_types
    assert TurnEnd in event_types
    assert AgentEnd in event_types

    # 验证 AgentEnd 正确结束
    agent_end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert agent_end.stop_reason == "end_turn"
    assert agent_end.final_text == "Hello world"
    assert agent_end.iterations == 1

    # 验证 messages 被正确填充
    assert len(messages) == 3
    assert messages[0].role == "system" and messages[0].content == "You are helpful"
    assert messages[1].role == "user" and messages[1].content == "Hi"
    assert messages[2].role == "assistant" and messages[2].content == "Hello world"


@pytest.mark.anyio
async def test_run_agent_loop_tool_execution_flow():
    """验证包含工具调用的多轮 ReAct 循环生命周期事件与保序写回。"""
    tc = [
        {
            "id": "call_mult",
            "type": "function",
            "function": {"name": "multiply", "arguments": json.dumps({"a": 3, "b": 7})},
        }
    ]
    llm = FakeLLM(
        [
            _response(tool_calls=tc),
            _response(content="Result is 21"),
        ]
    )
    registry = _make_registry(multiply)
    messages: list[Message] = []

    events = []
    async for ev in run_agent_loop(
        llm=llm,
        messages=messages,
        prompts=[Message(role="user", content="Calculate 3*7")],
        tools=registry,
    ):
        events.append(ev)

    # 验证成对的 ToolExecutionStart 和 ToolExecutionEnd
    starts = [e for e in events if isinstance(e, ToolExecutionStart)]
    ends = [e for e in events if isinstance(e, ToolExecutionEnd)]
    turn_ends = [e for e in events if isinstance(e, TurnEnd)]
    agent_ends = [e for e in events if isinstance(e, AgentEnd)]

    assert len(starts) == 1
    assert starts[0].tool_name == "multiply"
    assert starts[0].args == {"a": 3, "b": 7}

    assert len(ends) == 1
    assert ends[0].tool_name == "multiply"
    assert ends[0].result == "21"
    assert not ends[0].is_error

    # 2 轮 TurnStart / TurnEnd
    assert len(turn_ends) == 2
    assert len(agent_ends) == 1
    assert agent_ends[0].iterations == 2
    assert agent_ends[0].final_text == "Result is 21"

    # 验证最终上下文
    roles = [m.role for m in messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert messages[2].content == "21"
    assert messages[3].content == "Result is 21"


@pytest.mark.anyio
async def test_run_agent_loop_steering_message_harvesting():
    """验证 get_steering_messages 在内层循环结束前自动转向进入下一轮 Turn。"""
    steer_queue: list[Message] = []

    class SteeringLLM:
        def __init__(self):
            self.turn = 0

        async def achat_stream(self, *, messages, tools=None, **kwargs):
            self.turn += 1
            if self.turn == 1:
                # 模拟在 Turn 1 执行/流式过程中外部注入 steering
                steer_queue.append(Message(role="user", content="Wait, reconsider!"))
                yield StreamChunk(content="Initial thought", finish_reason="end_turn")
            else:
                yield StreamChunk(
                    content="Steered correction", finish_reason="end_turn"
                )

    def get_steering() -> Sequence[Message]:
        nonlocal steer_queue
        res = list(steer_queue)
        steer_queue.clear()
        return res

    llm = SteeringLLM()
    messages: list[Message] = []
    events = []
    async for ev in run_agent_loop(
        llm=llm,
        messages=messages,
        prompts=[Message(role="user", content="Plan the project")],
        get_steering_messages=get_steering,
    ):
        events.append(ev)

    agent_end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert agent_end.iterations == 2
    assert agent_end.final_text == "Steered correction"

    roles = [m.role for m in messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert messages[2].content == "Wait, reconsider!"
    assert messages[3].content == "Steered correction"


@pytest.mark.anyio
async def test_run_agent_loop_follow_up_harvesting():
    """验证 get_follow_up_messages 在内层循环彻底结束后驱动外层大循环继续处理后置任务。"""
    llm = FakeLLM(
        [
            _response(content="Done with step 1"),
            _response(content="Done with follow-up"),
        ]
    )

    follow_up_drained = False

    def get_follow_up() -> Sequence[Message]:
        nonlocal follow_up_drained
        if not follow_up_drained:
            follow_up_drained = True
            return [Message(role="user", content="Now do step 2")]
        return []

    messages: list[Message] = []
    events = []
    async for ev in run_agent_loop(
        llm=llm,
        messages=messages,
        prompts=[Message(role="user", content="Do step 1")],
        get_follow_up_messages=get_follow_up,
    ):
        events.append(ev)

    agent_end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert agent_end.iterations == 2
    assert agent_end.final_text == "Done with follow-up"

    roles = [m.role for m in messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert messages[2].content == "Now do step 2"
    assert messages[3].content == "Done with follow-up"


@pytest.mark.anyio
async def test_run_agent_loop_cancellation_with_token():
    """验证 CancellationToken 在工具执行前协作取消，合成中断结果并派发 stop_reason='cancelled'。"""
    tc = [
        {
            "id": "call_long",
            "type": "function",
            "function": {"name": "multiply", "arguments": json.dumps({"a": 2, "b": 2})},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc)])
    token = CancellationToken()

    messages: list[Message] = []
    events = []

    # 在捕获到 MessageUpdate 后触发取消
    async for ev in run_agent_loop(
        llm=llm,
        messages=messages,
        prompts=[Message(role="user", content="run tool")],
        tools=_make_registry(multiply),
        signal=token,
    ):
        events.append(ev)
        if isinstance(ev, MessageUpdate):
            token.cancel()

    agent_end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert agent_end.stop_reason == "cancelled"

    # 验证断头工具调用被立即自愈补齐
    assert len(messages) == 3
    assert messages[1].role == "assistant"
    assert messages[2].role == "tool"
    assert messages[2].metadata is not None
    assert messages[2].metadata["tool_call_id"] == "call_long"
    assert messages[2].metadata["is_error"] is True


@pytest.mark.anyio
async def test_run_agent_loop_max_turns_limit():
    """验证超过 max_turns 限制时停止循环并派发 stop_reason='max_iterations'。"""
    tc = [
        {
            "id": "call_loop",
            "type": "function",
            "function": {"name": "ping", "arguments": "{}"},
        }
    ]
    llm = FakeLLM(
        [
            _response(tool_calls=tc),
            _response(tool_calls=tc),
            _response(tool_calls=tc),
        ]
    )
    messages: list[Message] = []
    events = []

    async for ev in run_agent_loop(
        llm=llm,
        messages=messages,
        prompts=[Message(role="user", content="ping forever")],
        tools=_make_registry(ping),
        max_turns=1,
    ):
        events.append(ev)

    agent_end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert agent_end.stop_reason == "max_iterations"
    assert agent_end.iterations == 2


@pytest.mark.anyio
async def test_run_agent_loop_provider_context_cleaning_in_loop():
    """验证送入 LLM 的上下文通过 _provider_context 剥离历史空失败记录。"""
    llm = FakeLLM([_response(content="re-run ok")])
    # 历史记录包含一条之前失败残余的空 assistant(stop_reason="error")
    messages = [
        Message(role="user", content="prior task"),
        Message(role="assistant", content="", metadata={"stop_reason": "error"}),
    ]

    async for _ in run_agent_loop(
        llm=llm,
        messages=messages,
        prompts=[Message(role="user", content="retry now")],
    ):
        pass

    # 检查 LLM 收到的 messages 视图
    assert len(llm.calls) == 1
    call_msgs = llm.calls[0]["messages"]
    # 失败的空消息应已被 _provider_context 剔除
    assert not any(
        m.role == "assistant"
        and m.content == ""
        and m.metadata
        and m.metadata.get("stop_reason") == "error"
        for m in call_msgs
    )
    roles = [m.role for m in call_msgs]
    assert roles == ["user", "user"]


@pytest.mark.anyio
async def test_run_agent_loop_before_model_call_blocking():
    """验证 BeforeModelCall Hook 拦截模型调用。"""
    llm = FakeLLM([_response(content="should not be called")])
    messages: list[Message] = []
    hooks = HookRegistry()

    def block_before_call(event: BeforeModelCall) -> HookResult:
        return HookResult(block=True, reason="Blocked for safety")

    hooks.register(BeforeModelCall, block_before_call)

    events = []
    async for ev in run_agent_loop(
        llm=llm,
        messages=messages,
        prompts=[Message(role="user", content="unsafe input")],
        hook_registry=hooks,
    ):
        events.append(ev)

    agent_end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert agent_end.stop_reason == "blocked"
    assert len(llm.calls) == 0
