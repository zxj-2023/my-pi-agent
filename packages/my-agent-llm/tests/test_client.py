"""LLM 门面测试：路由、透传、构造、错误。"""
import pytest

from my_agent_llm import LLM, Config
from my_agent_llm.models import Message


def test_unknown_provider_raises():
    """未知 provider → ValueError。"""
    with pytest.raises(ValueError):
        LLM(config=Config(provider="nope", api_key="test"))


def test_missing_api_key_raises():
    """openai 无 api_key → ValueError。"""
    with pytest.raises(ValueError):
        LLM(config=Config(provider="openai"))


def test_config_or_kwargs_construction():
    """两种构造等价：传 Config 或散参。"""
    a = LLM(config=Config(provider="openai", api_key="k", model="m"))
    b = LLM(provider="openai", api_key="k", model="m")
    assert a.model == "m"
    assert b.model == "m"


def test_routes_to_provider():
    """provider 名 → 对应 provider 类。"""
    from my_agent_llm.providers.openai import OpenAIProvider
    from my_agent_llm.providers.deepseek import DeepSeekProvider
    from my_agent_llm.providers.anthropic import AnthropicProvider

    assert isinstance(LLM(config=Config(provider="openai", api_key="k"))._provider, OpenAIProvider)
    assert isinstance(LLM(config=Config(provider="deepseek", api_key="k"))._provider, DeepSeekProvider)
    assert isinstance(LLM(config=Config(provider="anthropic", api_key="k"))._provider, AnthropicProvider)


def test_chat_falls_back_to_config_sampling_params():
    """chat 未显式传 temperature/max_tokens → 用 config 值。"""
    from my_agent_llm.models import Response

    llm = LLM(config=Config(provider="openai", api_key="k", model="m", temperature=0.3, max_tokens=123))

    class FakeProvider:
        def __init__(self):
            self.calls = []

        def chat(self, messages, *, model, tools=None, **kwargs):
            self.calls.append(kwargs)
            return Response(content="ok", model=model)

    fp = FakeProvider()
    llm._provider = fp
    llm.chat([Message(role="user", content="hi")])
    assert fp.calls[0]["temperature"] == 0.3
    assert fp.calls[0]["max_tokens"] == 123
