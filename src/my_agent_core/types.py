"""Core protocol definitions and type aliases for agent runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from my_agent_llm.models import Message, Response, StreamChunk


@runtime_checkable
class LLMProtocol(Protocol):
    """LLM 客户端契约协议，支持流式与单次异步调用。"""

    async def achat(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> Response: ...

    def achat_stream(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]: ...

    def astream_events(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> Any: ...


@runtime_checkable
class ContextManagerProtocol(Protocol):
    """上下文压缩与视图管理协议。"""

    pending_compaction: Any

    async def prepare(self, messages: list[Message]) -> list[Message]: ...

    def record_usage(self, usage: dict[str, Any]) -> None: ...


__all__ = [
    "LLMProtocol",
    "ContextManagerProtocol",
]
