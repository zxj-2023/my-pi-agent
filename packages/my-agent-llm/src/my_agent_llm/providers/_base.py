"""Provider 抽象基类：统一接口，翻译全在子类内部。"""
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator

from ..models import Message, Response, StreamChunk


class Provider(ABC):
    """各 provider 的统一接口。"""

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
        yield  # 抽象标记：子类必须实现为异步生成器
