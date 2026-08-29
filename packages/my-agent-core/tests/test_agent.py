"""Agent 单层循环离线测试（假 LLM 替身，不碰真网络）。"""

import tempfile
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]
from my_agent_llm import (  # pyright: ignore[reportMissingImports]
    Message,
    Response,
    StreamChunk,
)

from my_agent_core.agent import Agent
from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    BeforeModelCall,
    HookResult,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
    UserInput,
)
from my_agent_core.session import Session
from my_agent_core.tools import tool


class FakeLLM:
    """替身：chat / achat_stream 按脚本返回 Response / StreamChunk，记录收到的 messages/tools。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        return self.responses.pop(0)

    async def achat(self, *, messages, tools=None, **kwargs) -> Response:
        return self.chat(messages=messages, tools=tools, **kwargs)

    async def achat_stream(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        resp = self.responses.pop(0)
        if resp.content:
            # 拆为两段 chunk 测试流式
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
def get_time() -> str:
    """Get the current time."""
    return "12:00"


def _response(content: str = "", tool_calls=None) -> Response:
    return Response(content=content, model="fake", tool_calls=tool_calls)


def _agent(llm, *, tools=(multiply,), session=None, **kwargs) -> Agent:
    if session is None:
        session = Session(path=Path(tempfile.mkdtemp()) / "s.jsonl")
    return Agent(llm=llm, tools=list(tools), session=session, **kwargs)


@pytest.mark.anyio
async def test_direct_answer():
    """直接回答路径：纯 content → 一轮结束返回文本（#2）。"""
    llm = FakeLLM([_response(content="hi")])
    agent = _agent(llm)
    answer = await agent.run("hello")
    assert answer == "hi"
    assert len(llm.calls) == 1


@pytest.mark.anyio
async def test_tool_call_then_answer():
    """工具调用路径：先 tool_calls 再纯 content → 循环执行 + 写回（#3）。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 6, "b": 7}'},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="42")])
    agent = _agent(llm)
    answer = await agent.run("compute")
    assert answer == "42"
    assert len(llm.calls) == 2


@pytest.mark.anyio
async def test_multiple_tool_calls():
    """一轮多个 tool_calls 各自配对写回（#4）。"""
    tcs = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'},
        },
        {
            "id": "2",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 4, "b": 5}'},
        },
    ]
    llm = FakeLLM([_response(tool_calls=tcs), _response(content="done")])
    agent = _agent(llm)
    answer = await agent.run("compute")
    assert answer == "done"
    second_call = llm.calls[1]["messages"]
    tool_msgs = [m for m in second_call if m.role == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[0].metadata["tool_call_id"] == "1"
    assert tool_msgs[1].metadata["tool_call_id"] == "2"
    assistant_msgs = [m for m in second_call if m.role == "assistant"]
    assert assistant_msgs[0].metadata["tool_calls"] == tcs


@pytest.mark.anyio
async def test_unknown_tool_error_recovered():
    """未知工具名 → 错误字符串写回，循环继续（#5）。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "nope", "arguments": "{}"},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="ok")])
    agent = _agent(llm)
    answer = await agent.run("do")
    assert answer == "ok"
    second_call = llm.calls[1]["messages"]
    tool_msgs = [m for m in second_call if m.role == "tool"]
    assert "Unknown tool 'nope'" in tool_msgs[0].content


@pytest.mark.anyio
async def test_messages_are_message_objects():
    """FakeLLM 收到的 messages 是 list[Message]，含 system（#14）。"""
    llm = FakeLLM([_response(content="hi")])
    agent = _agent(llm, system_prompt="be nice")
    await agent.run("hello")
    first_call = llm.calls[0]["messages"]
    assert all(isinstance(m, Message) for m in first_call)
    assert first_call[0].role == "system"
    assert first_call[0].content == "be nice"
    assert first_call[1].role == "user"


@pytest.mark.anyio
async def test_event_sequence():
    """事件序列完整顺序：AgentStart → Message(user) → TurnStart → Message(assistant) → ToolExecution → TurnEnd → ... → AgentEnd（#11）。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="6")])
    events = []
    agent = _agent(
        llm,
        hooks=[
            (cls, events.append)
            for cls in (
                AgentStart,
                MessageStart,
                MessageEnd,
                TurnStart,
                TurnEnd,
                ToolExecutionStart,
                ToolExecutionEnd,
                AgentEnd,
            )
        ],
    )
    await agent.run("compute")
    kinds = [type(e).__name__ for e in events]
    assert kinds == [
        "AgentStart",
        "MessageStart",
        "MessageEnd",
        "TurnStart",
        "MessageStart",
        "MessageEnd",
        "ToolExecutionStart",
        "ToolExecutionEnd",
        "MessageStart",
        "MessageEnd",
        "TurnEnd",
        "TurnStart",
        "MessageStart",
        "MessageEnd",
        "TurnEnd",
        "AgentEnd",
    ]
    # AgentEnd 携带 messages 与 stop_reason
    end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert end.final_text == "6"
    assert end.stop_reason == "end_turn"
    assert end.messages[-1].role == "assistant"


@pytest.mark.anyio
async def test_max_iterations():
    """max_iterations=1 且模型一直发 tool_calls → stop_reason="max_iterations"、final_text=None（#12）。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc)])  # 只有一轮 tool_calls，没有最终回答
    events = []
    agent = _agent(llm, max_iterations=1, hooks=[(AgentEnd, events.append)])
    answer = await agent.run("compute")
    assert answer is None
    end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert end.stop_reason == "max_iterations"
    assert end.final_text is None


@pytest.mark.anyio
async def test_agent_multiple_runs_and_reset():
    """连续两次 run 第二次含第一轮历史；reset 后只剩 system（#13）。"""
    llm = FakeLLM([_response(content="first"), _response(content="second")])
    agent = _agent(llm, system_prompt="sys")
    assert await agent.run("q1") == "first"
    assert await agent.run("q2") == "second"
    # 第二次请求含第一轮 user + assistant 历史
    second_call = llm.calls[1]["messages"]
    roles = [m.role for m in second_call]
    assert "user" in roles and "assistant" in roles
    # reset 后只剩 system
    agent.reset()
    assert [m.role for m in agent.messages] == ["system"]
    assert agent.messages[0].content == "sys"


@pytest.mark.anyio
async def test_hook_blocks_tool():
    """ToolExecutionStart hook 返回 block → 工具未执行，tool 消息含 blocked（#7）。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'},
        }
    ]
    called = []
    llm = FakeLLM([_response(tool_calls=tc), _response(content="blocked ok")])

    def guard(event):
        if isinstance(event, ToolExecutionStart):
            return HookResult(block=True, reason="no way")
        return None

    def probe(a: int, b: int) -> int:
        called.append((a, b))
        return a * b

    probe_tool = tool(probe)
    agent = _agent(llm, tools=[probe_tool], hooks=[(ToolExecutionStart, guard)])
    answer = await agent.run("compute")
    assert answer == "blocked ok"
    assert called == []  # 工具未执行
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "blocked: no way" in tool_msgs[0].content


@pytest.mark.anyio
async def test_hook_rewrites_args():
    """ToolExecutionStart hook 返回 updated_args → 工具收到改写值（#8）。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="done")])

    def rewrite(event):
        if isinstance(event, ToolExecutionStart):
            return HookResult(
                updated_args={"a": event.args["a"] * 10, "b": event.args["b"]}
            )
        return None

    agent = _agent(llm, hooks=[(ToolExecutionStart, rewrite)])
    await agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert tool_msgs[0].content == "60"  # 2*10 * 3


@pytest.mark.anyio
async def test_hook_rewrites_result():
    """ToolExecutionEnd hook 返回 updated_result → transcript 中是改写后的文本（#9）。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="done")])

    def rewrite(event):
        if isinstance(event, ToolExecutionEnd):
            return HookResult(updated_result=f"[{event.result}]")
        return None

    agent = _agent(llm, hooks=[(ToolExecutionEnd, rewrite)])
    await agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert tool_msgs[0].content == "[6]"


@pytest.mark.anyio
async def test_hook_exception_becomes_error():
    """hook 抛异常 → 转错误字符串，transcript 不变形（#10）。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="ok")])

    def boom(event):
        raise ValueError("boom")

    agent = _agent(llm, hooks=[(ToolExecutionStart, boom)])
    await agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "Error" in tool_msgs[0].content


@pytest.mark.anyio
async def test_tool_execution_end_hook_exception_becomes_error():
    """ToolExecutionEnd hook 抛异常 → 转错误字符串，工具已执行但结果被替换。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="ok")])

    def boom(event):
        raise ValueError("end boom")

    agent = _agent(llm, hooks=[(ToolExecutionEnd, boom)])
    await agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "Error" in tool_msgs[0].content  # 工具执行了，但结果被 End hook 异常替换


@pytest.mark.anyio
async def test_multiple_hooks_same_event():
    """同一事件挂多个 hook，按注册顺序触发，非 None 短路。"""
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'},
        }
    ]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="done")])
    order = []

    def first(event):
        order.append("first")
        return None  # 放行

    def second(event):
        order.append("second")
        return HookResult(updated_args={"a": 100, "b": 1})  # 短路

    def third(event):
        order.append("third")  # 不应被调用

    agent = _agent(
        llm,
        hooks=[
            (ToolExecutionStart, first),
            (ToolExecutionStart, second),
            (ToolExecutionStart, third),
        ],
    )
    await agent.run("compute")
    assert order == ["first", "second"]  # third 未触发（短路）
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert tool_msgs[0].content == "100"  # 第二个 hook 的改写生效


@pytest.mark.anyio
async def test_malformed_arguments_does_not_crash():
    """畸形/空 JSON 参数 → 错误写回 tool 消息，run() 不崩溃、正常结束（Important #1 修复验证）。"""
    for raw in ("not-json", ""):
        tc = [
            {
                "id": "1",
                "type": "function",
                "function": {"name": "multiply", "arguments": raw},
            }
        ]
        llm = FakeLLM([_response(tool_calls=tc), _response(content="recovered")])
        agent = _agent(llm)
        answer = await agent.run("compute")
        assert answer == "recovered"
        second_call = llm.calls[1]["messages"]
        tool_msgs = [m for m in second_call if m.role == "tool"]
        assert "Invalid JSON arguments" in tool_msgs[0].content
        assert tool_msgs[0].metadata["tool_call_id"] == "1"


@pytest.mark.anyio
async def test_model_passthrough():
    """Agent(model=) 透传给 llm.chat（子代理换模型的前置）。"""
    llm = FakeLLM([_response(content="hi")])
    agent = _agent(llm, model="sonnet")
    await agent.run("hello")
    assert llm.calls[0]["model"] == "sonnet"


@pytest.mark.anyio
async def test_agent_async_run_streaming_events():
    """Agent 流式运行期间逐 Token 发射 MessageUpdate 事件。"""
    llm = FakeLLM([_response(content="streaming hello world")])
    updates = []
    agent = _agent(llm, hooks=[(MessageUpdate, updates.append)])
    res = await agent.run("say hello")
    assert res == "streaming hello world"
    assert len(updates) >= 2
    assert all(isinstance(u, MessageUpdate) for u in updates)
    assert updates[-1].message.content == "streaming hello world"


@pytest.mark.anyio
async def test_agent_abort_cancels_and_discards_partial():
    """agent.abort() 触发取消，流式中断，半截文本不写入 Session，返回 (cancelled)。"""
    session = Session(path=Path(tempfile.mkdtemp()) / "session.jsonl")
    llm = FakeLLM([_response(content="half text that will be aborted")])

    agent = _agent(llm, session=session)

    # 注册一个 Hook 在收到第一个 chunk 时调用 agent.abort()
    def cancel_on_first_chunk(event: MessageUpdate):
        agent.abort()
        return None

    agent.hooks.register(MessageUpdate, cancel_on_first_chunk)

    result = await agent.run("test abort")
    assert result == "(cancelled)"

    # 验证 Session 中只有 user 消息，半截 assistant 文本未落盘
    entries = list(session.tree.entries.values())
    assert len(entries) == 1
    assert entries[0].role == "user"


@pytest.mark.anyio
async def test_message_update_hook_interception():
    """MessageUpdate Hook 返回 HookResult(block=True) 实时阻断流式并退出。"""
    session = Session(path=Path(tempfile.mkdtemp()) / "session.jsonl")
    llm = FakeLLM([_response(content="dangerous payload in stream")])
    agent = _agent(llm, session=session)

    def guard_hook(event: MessageUpdate):
        if "dangerous" in event.message.content:
            return HookResult(block=True, reason="Security alert")
        return None

    agent.hooks.register(MessageUpdate, guard_hook)

    result = await agent.run("danger test")
    assert result == "(cancelled)"
    # 半截文本被丢弃，Session 纯净
    assert not any(e.role == "assistant" for e in session.tree.entries.values())


@pytest.mark.anyio
async def test_agent_user_input_hook_block():
    """UserInput Hook 返回 block=True 阻断输入，不写 Session 且不调大模型。"""
    session = Session(path=Path(tempfile.mkdtemp()) / "session.jsonl")
    llm = FakeLLM([_response(content="should not be called")])
    agent = _agent(llm, session=session)

    def guard_input(event: UserInput):
        if "drop database" in event.input_text:
            return HookResult(block=True, reason="SQL injection detected")
        return None

    agent.hooks.register(UserInput, guard_input)

    result = await agent.run("drop database now")
    assert result == "(blocked: SQL injection detected)"
    # LLM 未被调用
    assert len(llm.calls) == 0
    # Session 纯净，没有任何 entry
    assert len(session.tree.entries) == 0


@pytest.mark.anyio
async def test_agent_user_input_hook_rewrite():
    """UserInput Hook 返回 updated_input 改写用户输入文本。"""
    session = Session(path=Path(tempfile.mkdtemp()) / "session.jsonl")
    llm = FakeLLM([_response(content="echo answer")])
    agent = _agent(llm, session=session)

    def rewrite_input(event: UserInput):
        if "foo" in event.input_text:
            return HookResult(updated_input=event.input_text.replace("foo", "bar"))
        return None

    agent.hooks.register(UserInput, rewrite_input)

    result = await agent.run("hello foo")
    assert result == "echo answer"
    # LLM 收到的 user 消息为改写后的文本
    assert llm.calls[0]["messages"][-1].content == "hello bar"
    # Session 记录的也是改写后的文本
    assert list(session.tree.entries.values())[0].content == "hello bar"


@pytest.mark.anyio
async def test_agent_agent_start_hook_rewrite_system_prompt():
    """AgentStart Hook 返回 updated_system_prompt 动态修改首条 system 消息。"""
    session = Session(path=Path(tempfile.mkdtemp()) / "session.jsonl")
    llm = FakeLLM([_response(content="persona answer")])
    agent = _agent(llm, session=session, system_prompt="Original Persona")

    def customize_system(event: AgentStart):
        return HookResult(updated_system_prompt="Customized Super Persona")

    agent.hooks.register(AgentStart, customize_system)

    result = await agent.run("who are you")
    assert result == "persona answer"
    # LLM 接收到的首条 system 消息已替换
    assert llm.calls[0]["messages"][0].content == "Customized Super Persona"


@pytest.mark.anyio
async def test_agent_before_model_call_hook_temporary_view_rewrite():
    """BeforeModelCall Hook 临时向 view 注入提醒，但 self.messages 与 Session 保持零污染。"""
    session = Session(path=Path(tempfile.mkdtemp()) / "session.jsonl")
    llm = FakeLLM([_response(content="model response")])
    agent = _agent(llm, session=session)

    def inject_ephemeral(event: BeforeModelCall):
        ephemeral = Message(role="user", content="[EPHEMERAL REMINDER: BE CONCISE]")
        return HookResult(updated_messages=list(event.messages) + [ephemeral])

    agent.hooks.register(BeforeModelCall, inject_ephemeral)

    result = await agent.run("do something")
    assert result == "model response"

    # 1. LLM 接收到的 view 中包含 ephemeral reminder
    last_call_messages = llm.calls[0]["messages"]
    assert any(
        "[EPHEMERAL REMINDER: BE CONCISE]" in m.content for m in last_call_messages
    )

    # 2. agent.messages 中绝不包含 ephemeral reminder
    assert not any(
        "[EPHEMERAL REMINDER: BE CONCISE]" in m.content for m in agent.messages
    )

    # 3. session 磁盘中绝不包含 ephemeral reminder
    session_contents = [e.content for e in session.tree.entries.values()]
    assert not any("[EPHEMERAL REMINDER: BE CONCISE]" in c for c in session_contents)
