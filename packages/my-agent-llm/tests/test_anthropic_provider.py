"""AnthropicProvider 双向翻译测试。"""
from my_agent_llm.config import Config
from my_agent_llm.models import Message
from my_agent_llm.providers.anthropic import AnthropicProvider
from tests.fake_anthropic import FakeAnthropic, make_anthropic_response


def _provider(responses):
    return AnthropicProvider(Config(api_key="test"), client=FakeAnthropic(responses))


def test_chat_splits_system_message():
    """system 消息 → 单独 system 参数。"""
    p = _provider([make_anthropic_response(text="hello")])
    p.chat(
        [Message(role="system", content="sys"), Message(role="user", content="hi")],
        model="claude-sonnet-4-5",
    )
    call = p.client.calls[0]
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_converts_tool_messages():
    """assistant tool_calls → tool_use block；tool 消息 → tool_result block。"""
    p = _provider([make_anthropic_response(text="done")])
    p.chat(
        [
            Message(role="assistant", content="let me", metadata={"tool_calls": [{"id": "1", "type": "function", "function": {"name": "f", "arguments": '{"x": 1}'}}]}),
            Message(role="tool", content="res", metadata={"tool_call_id": "1"}),
        ],
        model="claude-sonnet-4-5",
    )
    call = p.client.calls[0]
    # assistant → tool_use block
    assert call["messages"][0]["content"][0] == {"type": "text", "text": "let me"}
    assert call["messages"][0]["content"][1]["type"] == "tool_use"
    assert call["messages"][0]["content"][1]["name"] == "f"
    assert call["messages"][0]["content"][1]["input"] == {"x": 1}
    # tool → tool_result block（role 变 user）
    assert call["messages"][1]["role"] == "user"
    assert call["messages"][1]["content"][0]["type"] == "tool_result"
    assert call["messages"][1]["content"][0]["tool_use_id"] == "1"


def test_chat_extracts_text_and_tool_calls():
    """响应 content blocks → content + tool_calls。"""
    p = _provider([make_anthropic_response(text="answer", tool_uses=[{"id": "2", "name": "g", "input": {"y": 2}}])])
    resp = p.chat([Message(role="user", content="hi")], model="claude-sonnet-4-5")
    assert resp.content == "answer"
    assert resp.tool_calls == [{"id": "2", "type": "function", "function": {"name": "g", "arguments": '{"y": 2}'}}]


def test_chat_web_search_enhancement():
    """enable_web_search → 追加 web_search 内置工具。"""
    p = _provider([make_anthropic_response(text="ok")])
    p.chat(
        [Message(role="user", content="hi")],
        model="claude-sonnet-4-5",
        enable_web_search=True,
        web_search_max_uses=3,
    )
    call = p.client.calls[0]
    assert {"type": "web_search_20250305", "name": "web_search", "max_uses": 3} in call["tools"]
