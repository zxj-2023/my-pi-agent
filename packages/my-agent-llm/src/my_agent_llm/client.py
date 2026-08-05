"""LLM 门面：按 provider 路由到对应实现，对外一套 API，只透传不碰 SDK。"""
from collections.abc import AsyncIterator, Iterator

from .config import Config
from .models import Message, Response, StreamChunk
from .providers import Provider
from .providers.anthropic import AnthropicProvider
from .providers.deepseek import DeepSeekProvider
from .providers.openai import OpenAIProvider

_PROVIDER_CLASSES: dict[str, type[Provider]] = {
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "anthropic": AnthropicProvider,
}


class LLM:
    """统一 LLM 客户端：对外一套 API，屏蔽 provider 差异。"""

    def __init__(self, *, config: Config | None = None, **kwargs):
        """两种构造：传 Config 对象，或散参（内部包成 Config）。"""
        if config is None:
            config = Config(**kwargs)
        if config.provider not in _PROVIDER_CLASSES:
            raise ValueError(
                f"Unknown provider '{config.provider}'. "
                f"Available: {', '.join(sorted(_PROVIDER_CLASSES))}"
            )
        if not config.api_key:
            raise ValueError(f"No API key for provider: {config.provider}")
        provider_cls = _PROVIDER_CLASSES[config.provider]
        self._provider: Provider = provider_cls(config)
        self.config = config

    @property
    def model(self) -> str:
        """当前配置的模型名。"""
        if not self.config.model:
            raise ValueError("No model specified. Pass model=... or set Config.model.")
        return self.config.model

    def chat(self, messages: list[Message], *, tools: list[dict] | None = None,
             model: str | None = None, temperature: float | None = None,
             max_tokens: int | None = None, **kwargs) -> Response:
        """同步对话：完整历史 + 可选工具。核心方法。"""
        if temperature is not None:
            kwargs.setdefault("temperature", temperature)
        else:
            kwargs.setdefault("temperature", self.config.temperature)
        if max_tokens is not None:
            kwargs.setdefault("max_tokens", max_tokens)
        elif self.config.max_tokens is not None:
            kwargs.setdefault("max_tokens", self.config.max_tokens)
        return self._provider.chat(
            messages, model=model or self.model, tools=tools, **kwargs
        )

    def stream(self, messages: list[Message], *, tools: list[dict] | None = None,
               model: str | None = None, **kwargs) -> Iterator[StreamChunk]:
        """同步流式。"""
        return self._provider.stream(messages, model=model or self.model, tools=tools, **kwargs)

    async def achat(self, messages: list[Message], *, tools: list[dict] | None = None,
                    model: str | None = None, **kwargs) -> Response:
        """异步对话。"""
        return await self._provider.achat(messages, model=model or self.model, tools=tools, **kwargs)

    async def achat_stream(self, messages: list[Message], *, tools: list[dict] | None = None,
                           model: str | None = None, **kwargs) -> AsyncIterator[StreamChunk]:
        """异步流式。调用方直接 `async for chunk in llm.achat_stream(...)` 迭代，不 await。"""
        async for chunk in self._provider.achat_stream(
            messages, model=model or self.model, tools=tools, **kwargs
        ):
            yield chunk
