"""Provider 抽象基类：统一接口，翻译全在子类内部。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from typing import Any

from ..config import Config  # pyright: ignore[reportMissingImports]
from ..events import StreamEvent  # pyright: ignore[reportMissingImports]
from ..models import (  # pyright: ignore[reportMissingImports]
    Message,
    Response,
    StreamChunk,
)


class Provider(ABC):
    """各 provider 的统一接口。"""

    @abstractmethod
    def __init__(self, config: Config):
        """统一构造契约：所有 provider 都收 Config。"""

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Response:
        """同步对话。"""

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Iterator[StreamChunk]:
        """同步流式。"""

    @abstractmethod
    async def achat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Response:
        """异步对话。"""

    @abstractmethod
    async def achat_stream(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """异步流式。"""
        yield StreamChunk(
            content=""
        )  # 抽象标记：子类必须实现为异步生成器（基类永不执行）

    async def astream_events(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        signal: Any | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamEvent]:
        """异步高阶流式事件流（对标 Tau stream_response）。

        默认实现：使用 StreamAccumulator 包装底层 achat_stream 原始流。
        """
        from ..stream import (  # pyright: ignore[reportMissingImports]
            StreamAccumulator,
        )

        acc = StreamAccumulator()
        async for ev in acc.stream(
            self.achat_stream(messages, model=model, tools=tools, **kwargs),
            signal=signal,
        ):
            yield ev
