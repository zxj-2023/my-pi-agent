"""LLM 门面测试：路由、透传、构造、错误。"""

import pytest

from my_agent_llm import LLM, Config
from my_agent_llm.models import Message


def test_unknown_provider_raises():
    """未知 provider → ValueError。"""
    with pytest.raises(ValueError):
        LLM(Config(provider="nope", api_key="test"))


def test_missing_api_key_raises():
    """openai 无 api_key → ValueError。"""
    with pytest.raises(ValueError):
        LLM(Config(provider="openai"))


def test_config_construction():
    """标准工程构造：严格接收强类型 Config 对象。"""
    a = LLM(Config(provider="openai", api_key="k", model="m"))
    assert a.model == "m"
    assert a.config.provider == "openai"


def test_invalid_config_type_raises():
    """非 Config 实例传参 → 抛出明确的 TypeError。"""
    with pytest.raises(TypeError):
        LLM("not_a_config")  # pyright: ignore[reportArgumentType]


def test_routes_to_provider():
    """provider 名 → 对应 provider 类。"""
    from my_agent_llm.providers.anthropic import AnthropicProvider
    from my_agent_llm.providers.deepseek import DeepSeekProvider
    from my_agent_llm.providers.openai import OpenAIProvider

    assert isinstance(LLM(Config(provider="openai", api_key="k"))._provider, OpenAIProvider)
    assert isinstance(LLM(Config(provider="deepseek", api_key="k"))._provider, DeepSeekProvider)
    assert isinstance(LLM(Config(provider="anthropic", api_key="k"))._provider, AnthropicProvider)


def test_chat_falls_back_to_config_sampling_params():
    """未显式传参时，各方法统一回落到 config 采样默认值。"""
    from my_agent_llm.models import Response

    llm = LLM(
        Config(
            provider="openai",
            api_key="k",
            model="m",
            temperature=0.3,
            max_tokens=123,
        )
    )

    class FakeProvider:
        def __init__(self):
            self.calls = []

        def chat(self, messages, *, model, tools=None, **kwargs):
            _ = (messages, model, tools)
            self.calls.append(kwargs)
            return Response(content="ok", model=model)

    fp = FakeProvider()
    llm._provider = fp  # type: ignore[assignment]
    llm.chat([Message(role="user", content="hi")])
    assert fp.calls[0]["temperature"] == 0.3
    assert fp.calls[0]["max_tokens"] == 123


def test_chat_omits_max_tokens_when_config_none():
    """config.max_tokens=None → chat 不注入 max_tokens 键（anthropic 4096 回落不受影响）。"""
    from my_agent_llm.models import Response

    llm = LLM(Config(provider="openai", api_key="k", model="m"))

    class FakeProvider:
        def __init__(self):
            self.calls = []

        def chat(self, messages, *, model, tools=None, **kwargs):
            _ = (messages, model, tools)
            self.calls.append(kwargs)
            return Response(content="ok", model=model)

    fp = FakeProvider()
    llm._provider = fp  # type: ignore[assignment]
    llm.chat([Message(role="user", content="hi")])
    assert "max_tokens" not in fp.calls[0]
    assert fp.calls[0]["temperature"] == 0.7  # temperature 仍回落 config 默认
