"""Agent 单层循环离线测试（假 LLM 替身，不碰真网络）。"""
from my_agent_llm import Message, Response

from my_agent_core.agent import Agent, ToolBlocked
from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    AssistantMessageAdded,
    ToolCallEnd,
    ToolCallStart,
    TurnStart,
)
from my_agent_core.tools import ToolResult, tool


class FakeLLM:
    """替身：chat 按脚本返回 Response，记录收到的 messages/tools。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages), "tools": tools})
        return self.responses.pop(0)


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool
def get_time() -> str:
    """Get the current time."""
    return "12:00"


def _response(content: str = "", tool_calls=None) -> Response:
    return Response(content=content, model="fake", tool_calls=tool_calls)


def _agent(llm, *, tools=(multiply,), **kwargs) -> Agent:
    return Agent(llm=llm, tools=list(tools), **kwargs)


def test_direct_answer():
    """直接回答路径：纯 content → 一轮结束返回文本（#2）。"""
    llm = FakeLLM([_response(content="hi")])
    agent = _agent(llm)
    answer = agent.run("hello")
    assert answer == "hi"
    assert len(llm.calls) == 1


def test_tool_call_then_answer():
    """工具调用路径：先 tool_calls 再纯 content → 循环执行 + 写回（#3）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 6, "b": 7}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="42")])
    agent = _agent(llm)
    answer = agent.run("compute")
    assert answer == "42"
    assert len(llm.calls) == 2


def test_multiple_tool_calls():
    """一轮多个 tool_calls 各自配对写回（#4）。"""
    tcs = [
        {"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}},
        {"id": "2", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 4, "b": 5}'}},
    ]
    llm = FakeLLM([_response(tool_calls=tcs), _response(content="done")])
    agent = _agent(llm)
    answer = agent.run("compute")
    assert answer == "done"
    second_call = llm.calls[1]["messages"]
    tool_msgs = [m for m in second_call if m.role == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[0].metadata["tool_call_id"] == "1"
    assert tool_msgs[1].metadata["tool_call_id"] == "2"
    assistant_msgs = [m for m in second_call if m.role == "assistant"]
    assert assistant_msgs[0].metadata["tool_calls"] == tcs


def test_unknown_tool_error_recovered():
    """未知工具名 → 错误字符串写回，循环继续（#5）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "nope", "arguments": "{}"}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="ok")])
    agent = _agent(llm)
    answer = agent.run("do")
    assert answer == "ok"
    second_call = llm.calls[1]["messages"]
    tool_msgs = [m for m in second_call if m.role == "tool"]
    assert "Unknown tool 'nope'" in tool_msgs[0].content


def test_messages_are_message_objects():
    """FakeLLM 收到的 messages 是 list[Message]，含 system（#14）。"""
    llm = FakeLLM([_response(content="hi")])
    agent = _agent(llm, system_prompt="be nice")
    agent.run("hello")
    first_call = llm.calls[0]["messages"]
    assert all(isinstance(m, Message) for m in first_call)
    assert first_call[0].role == "system"
    assert first_call[0].content == "be nice"
    assert first_call[1].role == "user"


def test_event_sequence():
    """事件序列完整顺序：AgentStart → TurnStart → AssistantMessageAdded → ToolCallStart/End → ... → AgentEnd（#11）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="6")])
    events = []
    agent = _agent(llm, on_event=events.append)
    agent.run("compute")
    kinds = [type(e).__name__ for e in events]
    assert kinds[0] == "AgentStart"
    assert "TurnStart" in kinds
    assert kinds[-1] == "AgentEnd"
    assert any(isinstance(e, AssistantMessageAdded) for e in events)
    assert any(isinstance(e, ToolCallStart) for e in events)
    assert any(isinstance(e, ToolCallEnd) for e in events)
    # AgentEnd 携带最终文本与 stop_reason
    end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert end.final_text == "6"
    assert end.stop_reason == "end_turn"


def test_max_iterations():
    """max_iterations=1 且模型一直发 tool_calls → stop_reason="max_iterations"、final_text=None（#12）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc)])  # 只有一轮 tool_calls，没有最终回答
    events = []
    agent = _agent(llm, max_iterations=1, on_event=events.append)
    answer = agent.run("compute")
    assert answer is None
    end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert end.stop_reason == "max_iterations"
    assert end.final_text is None


def test_agent_multiple_runs_and_reset():
    """连续两次 run 第二次含第一轮历史；reset 后只剩 system（#13）。"""
    llm = FakeLLM([_response(content="first"), _response(content="second")])
    agent = _agent(llm, system_prompt="sys")
    assert agent.run("q1") == "first"
    assert agent.run("q2") == "second"
    # 第二次请求含第一轮 user + assistant 历史
    second_call = llm.calls[1]["messages"]
    roles = [m.role for m in second_call]
    assert "user" in roles and "assistant" in roles
    # reset 后只剩 system
    agent.reset()
    assert [m.role for m in agent.messages] == ["system"]
    assert agent.messages[0].content == "sys"


def test_before_tool_blocks():
    """before_tool 抛 ToolBlocked → tool 消息含 "blocked"，工具函数未被调用（#7）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    called = []
    llm = FakeLLM([_response(tool_calls=tc), _response(content="blocked ok")])

    def guard(name, args):
        raise ToolBlocked("no way")

    def probe(a: int, b: int) -> int:
        called.append((a, b))
        return a * b

    probe_tool = tool(probe)
    agent = Agent(llm=llm, tools=[probe_tool], before_tool=guard)
    answer = agent.run("compute")
    assert answer == "blocked ok"
    assert called == []  # 工具函数未被调用
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "blocked: no way" in tool_msgs[0].content


def test_before_tool_rewrites_args():
    """before_tool 返回改写的 args → 工具收到改写值；ToolCallStart 携带改写后 args（#8）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="done")])

    def rewrite(name, args):
        return {"a": args["a"] * 10, "b": args["b"]}

    events = []
    agent = Agent(llm=llm, tools=[multiply], before_tool=rewrite, on_event=events.append)
    agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert tool_msgs[0].content == "60"  # 2*10 * 3
    start = [e for e in events if isinstance(e, ToolCallStart)][0]
    assert start.args == {"a": 20, "b": 3}  # ToolCallStart 携带 before_tool 改写后的参数


def test_after_tool_rewrites_result():
    """after_tool 返回改写 result → transcript 中是改写后的文本（#9）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="done")])

    def rewrite(name, args, result):
        return ToolResult(ok=True, data=f"[{result.data}]")

    agent = Agent(llm=llm, tools=[multiply], after_tool=rewrite)
    agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert tool_msgs[0].content == "[6]"


def test_middleware_exception_becomes_error():
    """中间件抛其他异常 → 转错误字符串，transcript 不变形（#10）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="ok")])

    def boom(name, args):
        raise ValueError("boom")

    agent = Agent(llm=llm, tools=[multiply], before_tool=boom)
    agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "Error in before_tool" in tool_msgs[0].content


def test_after_tool_exception_becomes_error():
    """after_tool 抛异常 → 转错误字符串，transcript 不变形（#10 补）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="ok")])

    def boom(name, args, result):
        raise ValueError("after boom")

    agent = Agent(llm=llm, tools=[multiply], after_tool=boom)
    agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "Error in after_tool" in tool_msgs[0].content


def test_malformed_arguments_does_not_crash():
    """畸形/空 JSON 参数 → 错误写回 tool 消息，run() 不崩溃、正常结束（Important #1 修复验证）。"""
    for raw in ("not-json", ""):
        tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": raw}}]
        llm = FakeLLM([_response(tool_calls=tc), _response(content="recovered")])
        agent = _agent(llm)
        answer = agent.run("compute")
        assert answer == "recovered"
        second_call = llm.calls[1]["messages"]
        tool_msgs = [m for m in second_call if m.role == "tool"]
        assert "Invalid JSON arguments" in tool_msgs[0].content
        assert tool_msgs[0].metadata["tool_call_id"] == "1"
