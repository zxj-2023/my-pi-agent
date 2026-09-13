# pyright: reportUnreachable=false
"""LLM 门面：按 provider 路由到对应实现，对外一套 API，只透传不碰 SDK。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

from .config import Config  # pyright: ignore[reportMissingImports]
from .events import StreamEvent  # pyright: ignore[reportMissingImports]
from .models import (  # pyright: ignore[reportMissingImports]
    Message,
    Response,
    StreamChunk,
)
from .providers import Provider  # pyright: ignore[reportMissingImports]
from .providers.registry import (
    PROVIDER_REGISTRY,  # pyright: ignore[reportMissingImports]
)


class LLM:
    """统一 LLM 客户端门面：严格接收强类型 Config 配置，多态路由至具体 Provider。"""

    def __init__(self, config: Config) -> None:
        """标准工程构造：严格接收 Config 实例。"""
        if not isinstance(config, Config):  # pyright: ignore[reportUnreachable]
            raise TypeError(f"LLM expects a Config instance, got {type(config).__name__}")  # pyright: ignore[reportUnreachable]
        if config.provider not in PROVIDER_REGISTRY:
            raise ValueError(f"Unknown provider '{config.provider}'. Available: {', '.join(sorted(PROVIDER_REGISTRY))}")
        if not config.api_key and config.provider != "antigravity":
            raise ValueError(f"No API key for provider: {config.provider}")
        provider_cls = PROVIDER_REGISTRY[config.provider]
        self._provider: Provider = provider_cls(config)
        self.config = config

    @property
    def model(self) -> str:
        """当前配置的模型名。"""
        if not self.config.model:
            raise ValueError("No model specified. Pass model=... or set Config.model.")
        return self.config.model

    def _resolve_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """统一合并调用参数与全局 Config 中的默认采样配置。"""
        opts = dict(kwargs)
        if self.config.temperature is not None:
            opts.setdefault("temperature", self.config.temperature)
        if self.config.max_tokens is not None:
            opts.setdefault("max_tokens", self.config.max_tokens)
        return opts

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Response:
        """同步对话：完整历史 + 可选工具。"""
        opts = self._resolve_kwargs(kwargs)
        return self._provider.chat(messages, model=model or self.model, tools=tools, **opts)

    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        """同步流式。"""
        opts = self._resolve_kwargs(kwargs)
        return self._provider.stream(messages, model=model or self.model, tools=tools, **opts)

    async def achat(
        self,
        messages: list[Message],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Response:
        """异步对话。"""
        opts = self._resolve_kwargs(kwargs)
        return await self._provider.achat(messages, model=model or self.model, tools=tools, **opts)

    async def achat_stream(
        self,
        messages: list[Message],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """异步流式。调用方直接 `async for chunk in llm.achat_stream(...)` 迭代，不 await。"""
        opts = self._resolve_kwargs(kwargs)
        async for chunk in self._provider.achat_stream(messages, model=model or self.model, tools=tools, **opts):
            yield chunk

    async def astream_events(
        self,
        messages: list[Message],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        signal: Any | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """异步高阶流式事件流：直接产出 StreamStartEvent/TextDeltaEvent/StreamDoneEvent/StreamErrorEvent。"""
        opts = self._resolve_kwargs(kwargs)
        async for ev in self._provider.astream_events(
            messages, model=model or self.model, tools=tools, signal=signal, **opts
        ):
            yield ev
