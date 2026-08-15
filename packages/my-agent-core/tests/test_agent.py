"""Agent 单层循环离线测试（假 LLM 替身，不碰真网络）。"""
from my_agent_llm import Message, Response

from my_agent_core.agent import Agent
from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    HookResult,
    MessageEnd,
    MessageStart,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
)
from my_agent_core.tools import tool


class FakeLLM:
    """替身：chat 按脚本返回 Response，记录收到的 messages/tools。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
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
    """事件序列完整顺序：AgentStart → Message(user) → TurnStart → Message(assistant) → ToolExecution → TurnEnd → ... → AgentEnd（#11）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="6")])
    events = []
    agent = _agent(llm)
    for cls in (AgentStart, MessageStart, MessageEnd, TurnStart, TurnEnd,
                ToolExecutionStart, ToolExecutionEnd, AgentEnd):
        agent.register_hook(cls, events.append)
    agent.run("compute")
    kinds = [type(e).__name__ for e in events]
    assert kinds == [
        "AgentStart", "MessageStart", "MessageEnd", "TurnStart",
        "MessageStart", "MessageEnd", "ToolExecutionStart", "ToolExecutionEnd",
        "MessageStart", "MessageEnd", "TurnEnd",
        "TurnStart", "MessageStart", "MessageEnd", "AgentEnd",
    ]
    # AgentEnd 携带 messages 与 stop_reason
    end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert end.final_text == "6"
    assert end.stop_reason == "end_turn"
    assert end.messages[-1].role == "assistant"


def test_max_iterations():
    """max_iterations=1 且模型一直发 tool_calls → stop_reason="max_iterations"、final_text=None（#12）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc)])  # 只有一轮 tool_calls，没有最终回答
    events = []
    agent = _agent(llm, max_iterations=1)
    agent.register_hook(AgentEnd, events.append)
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


def test_hook_blocks_tool():
    """ToolExecutionStart hook 返回 block → 工具未执行，tool 消息含 blocked（#7）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
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
    agent = Agent(llm=llm, tools=[probe_tool])
    agent.register_hook(ToolExecutionStart, guard)
    answer = agent.run("compute")
    assert answer == "blocked ok"
    assert called == []  # 工具未执行
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "blocked: no way" in tool_msgs[0].content


def test_hook_rewrites_args():
    """ToolExecutionStart hook 返回 updated_args → 工具收到改写值（#8）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="done")])

    def rewrite(event):
        if isinstance(event, ToolExecutionStart):
            return HookResult(updated_args={"a": event.args["a"] * 10, "b": event.args["b"]})
        return None

    agent = Agent(llm=llm, tools=[multiply])
    agent.register_hook(ToolExecutionStart, rewrite)
    agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert tool_msgs[0].content == "60"  # 2*10 * 3


def test_hook_rewrites_result():
    """ToolExecutionEnd hook 返回 updated_result → transcript 中是改写后的文本（#9）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="done")])

    def rewrite(event):
        if isinstance(event, ToolExecutionEnd):
            return HookResult(updated_result=f"[{event.result}]")
        return None

    agent = Agent(llm=llm, tools=[multiply])
    agent.register_hook(ToolExecutionEnd, rewrite)
    agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert tool_msgs[0].content == "[6]"


def test_hook_exception_becomes_error():
    """hook 抛异常 → 转错误字符串，transcript 不变形（#10）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="ok")])

    def boom(event):
        raise ValueError("boom")

    agent = Agent(llm=llm, tools=[multiply])
    agent.register_hook(ToolExecutionStart, boom)
    agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "Error" in tool_msgs[0].content


def test_tool_execution_end_hook_exception_becomes_error():
    """ToolExecutionEnd hook 抛异常 → 转错误字符串，工具已执行但结果被替换。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="ok")])

    def boom(event):
        raise ValueError("end boom")

    agent = Agent(llm=llm, tools=[multiply])
    agent.register_hook(ToolExecutionEnd, boom)
    agent.run("compute")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "Error" in tool_msgs[0].content  # 工具执行了，但结果被 End hook 异常替换


def test_multiple_hooks_same_event():
    """同一事件挂多个 hook，按注册顺序触发，非 None 短路。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}}]
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

    agent = Agent(llm=llm, tools=[multiply])
    agent.register_hook(ToolExecutionStart, first)
    agent.register_hook(ToolExecutionStart, second)
    agent.register_hook(ToolExecutionStart, third)
    agent.run("compute")
    assert order == ["first", "second"]  # third 未触发（短路）
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert tool_msgs[0].content == "100"  # 第二个 hook 的改写生效


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


def test_model_passthrough():
    """Agent(model=) 透传给 llm.chat（子代理换模型的前置）。"""
    llm = FakeLLM([_response(content="hi")])
    agent = Agent(llm=llm, tools=[multiply], model="sonnet")
    agent.run("hello")
    assert llm.calls[0]["model"] == "sonnet"
