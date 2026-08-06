"""OpenAIProvider 翻译测试（假 SDK）。"""
from types import SimpleNamespace

from my_agent_llm.config import Config
from my_agent_llm.models import Message, Response
from my_agent_llm.providers.openai import OpenAIProvider
from tests.fakes import FakeOpenAI, make_openai_response


def _provider(responses):
    return OpenAIProvider(Config(api_key="test"), client=FakeOpenAI(responses))


def test_chat_returns_response():
    """chat → Response：content/model/usage/finish_reason。"""
    p = _provider([make_openai_response(content="hello")])
    resp = p.chat([Message(role="user", content="hi")], model="gpt-4.1-mini")
    assert isinstance(resp, Response)
    assert resp.content == "hello"
    assert resp.model == "gpt-4.1-mini"
    assert resp.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert resp.finish_reason == "stop"


def test_chat_passes_messages_and_tools():
    """chat → SDK 收到正确 messages/tools。"""
    p = _provider([make_openai_response()])
    tools = [{"type": "function", "function": {"name": "f", "description": "", "parameters": {}}}]
    p.chat(
        [Message(role="user", content="hi")],
        model="gpt-4.1-mini",
        tools=tools,
        temperature=0.5,
    )
    call = p.client.calls[0]
    assert call["model"] == "gpt-4.1-mini"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert call["tools"] == tools
    assert call["temperature"] == 0.5


def test_chat_converts_tool_messages():
    """tool 消息 → wire dict 带 tool_call_id。"""
    p = _provider([make_openai_response()])
    p.chat(
        [
            Message(role="assistant", content="", metadata={"tool_calls": [{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}),
            Message(role="tool", content="result", metadata={"tool_call_id": "1"}),
        ],
        model="gpt-4.1-mini",
    )
    call = p.client.calls[0]
    assert call["messages"][0] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
    }
    assert call["messages"][1] == {"role": "tool", "content": "result", "tool_call_id": "1"}


def test_chat_extracts_tool_calls():
    """响应 tool_calls → Response.tool_calls（统一 OpenAI 形状）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
    p = _provider([make_openai_response(tool_calls=tc)])
    resp = p.chat([Message(role="user", content="hi")], model="gpt-4.1-mini")
    assert resp.tool_calls == tc


def test_stream_yields_chunks():
    """stream → 文本增量序列；usage-only 末块（choices 为空）跳过。"""
    class FakeStream:
        def __init__(self):
            self.chunks = [
                SimpleNamespace(id="1", choices=[SimpleNamespace(delta=SimpleNamespace(content="a"), finish_reason=None)]),
                SimpleNamespace(id="2", choices=[SimpleNamespace(delta=SimpleNamespace(content="b"), finish_reason="stop")]),
                SimpleNamespace(id="3", choices=[]),  # usage-only 末块
            ]
        def __iter__(self):
            return iter(self.chunks)

    p = _provider([])
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: FakeStream())))
    chunks = list(p.stream([Message(role="user", content="hi")], model="gpt-4.1-mini"))
    assert [c.content for c in chunks] == ["a", "b"]


def test_stream_aggregates_tool_calls():
    """流式增量 tool_calls → 末块聚合完整（id/name 来一次、arguments 碎片拼接）。"""
    class FakeStream:
        def __init__(self):
            self.chunks = [
                # 工具调用增量片段：index 0，id + name 只出现在第一片
                SimpleNamespace(id="1", choices=[SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[SimpleNamespace(
                            index=0, id="call_1",
                            function=SimpleNamespace(name="get_weather", arguments=""),
                        )],
                    ),
                    finish_reason=None,
                )], usage=None),
                SimpleNamespace(id="2", choices=[SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[SimpleNamespace(
                            index=0, id=None,
                            function=SimpleNamespace(name=None, arguments='{"city":'),
                        )],
                    ),
                    finish_reason=None,
                )], usage=None),
                SimpleNamespace(id="3", choices=[SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[SimpleNamespace(
                            index=0, id=None,
                            function=SimpleNamespace(name=None, arguments='"Tokyo"}'),
                        )],
                    ),
                    finish_reason="tool_calls",
                )], usage=None),
                SimpleNamespace(id="4", choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)),
            ]
        def __iter__(self):
            return iter(self.chunks)

    p = _provider([])
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: FakeStream())))
    chunks = list(p.stream([Message(role="user", content="hi")], model="gpt-4.1-mini"))
    # 无文本增量（content=None），只剩一个聚合末块
    assert [c.content for c in chunks] == [""]
    assert chunks[0].tool_calls == [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":"Tokyo"}'},
    }]
    assert chunks[0].usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
