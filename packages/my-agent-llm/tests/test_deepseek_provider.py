"""DeepSeekProvider 翻译测试：OpenAI 兼容 + reasoning 提取。"""
from types import SimpleNamespace

from my_agent_llm.config import Config
from my_agent_llm.models import Message
from my_agent_llm.providers.deepseek import DeepSeekProvider
from tests.fakes import FakeOpenAI


def _provider(responses):
    return DeepSeekProvider(Config(api_key="test"), client=FakeOpenAI(responses))


def test_chat_extracts_reasoning():
    """响应 reasoning_content → Response.reasoning_content。"""
    from tests.fakes import make_openai_response

    resp = make_openai_response(content="answer")
    resp.choices[0].message.reasoning_content = "thinking..."
    p = _provider([resp])
    out = p.chat([Message(role="user", content="hi")], model="deepseek-chat")
    assert out.content == "answer"
    assert out.reasoning_content == "thinking..."


def test_default_base_url_deepseek():
    """构造时默认 base_url 指向 deepseek。"""
    p = DeepSeekProvider(Config(api_key="test"))
    assert p.config.base_url == "https://api.deepseek.com"


def test_stream_aggregates_tool_calls_and_reasoning():
    """流式增量 tool_calls + reasoning → 末块聚合完整。"""
    class FakeStream:
        def __init__(self):
            self.chunks = [
                SimpleNamespace(id="1", choices=[SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        reasoning_content="think",
                        tool_calls=[SimpleNamespace(
                            index=0, id="call_1",
                            function=SimpleNamespace(name="f", arguments=""),
                        )],
                    ),
                    finish_reason=None,
                )], usage=None),
                SimpleNamespace(id="2", choices=[SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        reasoning_content="ing",
                        tool_calls=[SimpleNamespace(
                            index=0, id=None,
                            function=SimpleNamespace(name=None, arguments="{}"),
                        )],
                    ),
                    finish_reason="tool_calls",
                )], usage=None),
                SimpleNamespace(id="3", choices=[], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5)),
            ]
        def __iter__(self):
            return iter(self.chunks)

    p = _provider([])
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: FakeStream())))
    chunks = list(p.stream([Message(role="user", content="hi")], model="deepseek-chat"))
    assert [c.content for c in chunks] == [""]
    last = chunks[0]
    assert last.tool_calls == [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "f", "arguments": "{}"},
    }]
    assert last.metadata == {"reasoning_content": "thinking"}
    assert last.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert last.finish_reason == "tool_calls"  # 末块透传循环内捕获的 finish_reason
