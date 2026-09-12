# ruff: noqa: S105, S106
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from my_agent_llm.auth.antigravity import AntigravityCredentials
from my_agent_llm.client import LLM
from my_agent_llm.config import Config
from my_agent_llm.models import Message
from my_agent_llm.providers.antigravity import (  # pyright: ignore[reportMissingImports]
    AntigravityProvider,
)
from my_agent_llm.providers.registry import PROVIDER_REGISTRY
from tests.fakes import FakeOpenAI, make_openai_response


def test_antigravity_provider_initialization():
    cfg = Config(provider="antigravity", model="gemini-3.8-flash")
    provider = AntigravityProvider(cfg)
    assert "cloudcode-pa.googleapis.com" in provider.base_url
    assert provider.config.model == "gemini-3.8-flash"


@pytest.mark.anyio
async def test_antigravity_provider_headers_injection():
    cfg = Config(
        provider="antigravity",
        model="gemini-3.8-flash",
        api_key="ya29.mock_token",
    )
    provider = AntigravityProvider(cfg)
    headers = provider._build_headers()
    assert headers["Authorization"] == "Bearer ya29.mock_token"
    assert headers["x-goog-user-project"] == "aicode-consumers"
    assert "antigravity/cli" in headers["User-Agent"]
    assert headers["Content-Type"] == "application/json"


def test_antigravity_provider_resolves_credentials_from_resolver():
    mock_creds = AntigravityCredentials(
        access_token="ya29.resolved_token",
        refresh_token="1//refresh",
        project_id="custom-project-id",
    )
    with patch(
        "my_agent_llm.providers.antigravity.AntigravityAuthResolver.get_valid_credentials",
        return_value=mock_creds,
    ):
        cfg = Config(provider="antigravity", model="gemini-1.5-pro")
        provider = AntigravityProvider(cfg)
        assert provider.config.api_key == "ya29.resolved_token"
        assert provider.project_id == "custom-project-id"
        headers = provider._build_headers()
        assert headers["Authorization"] == "Bearer ya29.resolved_token"
        assert headers["x-goog-user-project"] == "custom-project-id"


def test_antigravity_provider_custom_base_url_and_env_project_id(monkeypatch):
    monkeypatch.setenv("ANTIGRAVITY_BASE_URL", "https://custom.endpoint.com")
    monkeypatch.setenv("ANTIGRAVITY_PROJECT_ID", "env-project-456")

    cfg = Config(provider="antigravity", model="gemini-1.5-flash", api_key="test-key")
    provider = AntigravityProvider(cfg)
    assert provider.base_url == "https://custom.endpoint.com"
    assert provider.project_id == "env-project-456"
    headers = provider._build_headers()
    assert headers["x-goog-user-project"] == "env-project-456"


def test_antigravity_provider_in_registry():
    assert "antigravity" in PROVIDER_REGISTRY
    assert PROVIDER_REGISTRY["antigravity"] is AntigravityProvider


def test_llm_routes_to_antigravity_provider():
    llm = LLM(Config(provider="antigravity", api_key="ya29.test", model="gemini-1.5-pro"))
    assert isinstance(llm._provider, AntigravityProvider)
    assert llm.model == "gemini-1.5-pro"


def test_antigravity_provider_chat_with_fake():
    resp = make_openai_response(
        content="Hello from Antigravity!", model="gemini-1.5-flash"
    )
    fake_client = FakeOpenAI([resp])
    cfg = Config(
        provider="antigravity", model="gemini-1.5-flash", api_key="ya29.test"
    )
    provider = AntigravityProvider(cfg, client=fake_client)

    out = provider.chat(
        [Message(role="user", content="hello")],
        model="gemini-1.5-flash",
    )
    assert out.content == "Hello from Antigravity!"
    assert out.model == "gemini-1.5-flash"


def test_antigravity_provider_stream_with_fake():
    class FakeStream:
        def __init__(self):
            self.chunks = [
                SimpleNamespace(
                    id="1",
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Hello",
                                tool_calls=None,
                            ),
                            finish_reason=None,
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    id="2",
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=" world",
                                tool_calls=None,
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    id="3",
                    choices=[],
                    usage=SimpleNamespace(
                        prompt_tokens=5, completion_tokens=3, total_tokens=8
                    ),
                ),
            ]

        def __iter__(self):
            return iter(self.chunks)

    cfg = Config(
        provider="antigravity", model="gemini-1.5-flash", api_key="ya29.test"
    )
    provider = AntigravityProvider(cfg)
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: FakeStream())
        )
    )

    chunks = list(
        provider.stream(
            [Message(role="user", content="hi")],
            model="gemini-1.5-flash",
        )
    )
    assert len(chunks) == 3
    assert chunks[0].content == "Hello"
    assert chunks[1].content == " world"
    assert chunks[2].content == ""
    assert chunks[2].response is not None
    assert chunks[2].response.content == "Hello world"
    assert chunks[2].usage == {
        "prompt_tokens": 5,
        "completion_tokens": 3,
        "total_tokens": 8,
    }


@pytest.mark.anyio
async def test_antigravity_provider_achat_with_fake():
    resp = make_openai_response(
        content="Async hello!", model="gemini-1.5-pro"
    )
    mock_async_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=pytest.importorskip("unittest.mock").AsyncMock(return_value=resp)
            )
        )
    )
    cfg = Config(
        provider="antigravity", model="gemini-1.5-pro", api_key="ya29.test"
    )
    provider = AntigravityProvider(cfg, async_client=mock_async_client)

    out = await provider.achat(
        [Message(role="user", content="hello async")],
        model="gemini-1.5-pro",
    )
    assert out.content == "Async hello!"
    assert out.model == "gemini-1.5-pro"


@pytest.mark.anyio
async def test_antigravity_provider_achat_stream_with_fake():
    class AsyncFakeStream:
        def __init__(self):
            self.chunks = [
                SimpleNamespace(
                    id="1",
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Async stream",
                                tool_calls=None,
                            ),
                            finish_reason=None,
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    id="2",
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=" done",
                                tool_calls=None,
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    id="3",
                    choices=[],
                    usage=SimpleNamespace(
                        prompt_tokens=4, completion_tokens=2, total_tokens=6
                    ),
                ),
            ]

        def __aiter__(self):
            self._iter = iter(self.chunks)
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration from None

    mock_async_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=pytest.importorskip("unittest.mock").AsyncMock(
                    return_value=AsyncFakeStream()
                )
            )
        )
    )
    cfg = Config(
        provider="antigravity", model="gemini-1.5-pro", api_key="ya29.test"
    )
    provider = AntigravityProvider(cfg, async_client=mock_async_client)

    chunks = []
    async for chunk in provider.achat_stream(
        [Message(role="user", content="hi async stream")],
        model="gemini-1.5-pro",
    ):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0].content == "Async stream"
    assert chunks[1].content == " done"
    assert chunks[2].content == ""
    assert chunks[2].response is not None
    assert chunks[2].response.content == "Async stream done"
    assert chunks[2].usage == {
        "prompt_tokens": 4,
        "completion_tokens": 2,
        "total_tokens": 6,
    }

