"""run_agent 循环离线测试（假 LLM 替身，不碰真网络）。"""
from my_agent_llm import Message, Response

from my_agent_core.agent import run_agent
from my_agent_core.tools import tool


class FakeLLM:
    """替身：chat 按脚本返回 Response，记录收到的 messages/tools。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": messages, "tools": tools})
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


def test_direct_answer():
    """直接回答路径：纯 content → 一轮结束返回文本。"""
    llm = FakeLLM([_response(content="hi")])
    answer = run_agent("hello", tools=[multiply], llm=llm)
    assert answer == "hi"
    assert len(llm.calls) == 1


def test_tool_call_then_answer():
    """工具调用路径：先 tool_calls 再纯 content → 循环执行 + 写回。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 6, "b": 7}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="42")])
    answer = run_agent("compute", tools=[multiply], llm=llm)
    assert answer == "42"
    assert len(llm.calls) == 2


def test_multiple_tool_calls():
    """一轮多个 tool_calls 各自配对写回。"""
    tcs = [
        {"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}},
        {"id": "2", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 4, "b": 5}'}},
    ]
    llm = FakeLLM([_response(tool_calls=tcs), _response(content="done")])
    answer = run_agent("compute", tools=[multiply], llm=llm)
    assert answer == "done"
    # 第二轮的 messages 应含 2 条 tool 消息（各自配对 tool_call_id）
    second_call = llm.calls[1]["messages"]
    tool_msgs = [m for m in second_call if m.role == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[0].metadata["tool_call_id"] == "1"
    assert tool_msgs[1].metadata["tool_call_id"] == "2"


def test_unknown_tool_error_recovered():
    """未知工具名 → 错误字符串写回，循环继续。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "nope", "arguments": "{}"}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="ok")])
    answer = run_agent("do", tools=[multiply], llm=llm)
    assert answer == "ok"
    second_call = llm.calls[1]["messages"]
    tool_msgs = [m for m in second_call if m.role == "tool"]
    assert "Unknown tool 'nope'" in tool_msgs[0].content


def test_messages_are_message_objects():
    """FakeLLM 收到的 messages 是 list[Message]，含 system。"""
    llm = FakeLLM([_response(content="hi")])
    run_agent("hello", tools=[multiply], llm=llm, system_prompt="be nice")
    first_call = llm.calls[0]["messages"]
    assert all(isinstance(m, Message) for m in first_call)
    assert first_call[0].role == "system"
    assert first_call[0].content == "be nice"
    assert first_call[1].role == "user"
