"""DeepSeekProvider 翻译测试：OpenAI 兼容 + reasoning 提取。"""
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
