"""DeepSeek provider：OpenAI 兼容端点 + reasoning_content 提取。"""
from collections.abc import AsyncIterator, Iterator

from ..config import Config
from ..models import Message, Response, StreamChunk
from .openai import OpenAIProvider, _ToolCallAccumulator


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek provider：复用 OpenAI 兼容翻译，额外提取 reasoning_content。"""

    def __init__(self, config: Config, client=None, async_client=None):
        """初始化。默认 base_url 指向 deepseek。"""
        if client is None and config.base_url is None:
            config = config.model_copy(update={"base_url": "https://api.deepseek.com"})
        super().__init__(config, client=client, async_client=async_client)

    @staticmethod
    def _extract_reasoning(message) -> str | None:
        """提取 reasoning_content（推理模型思考内容）。"""
        return getattr(message, "reasoning_content", None) or None

    def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Response:
        response = self.client.chat.completions.create(
            model=model,
            messages=self._convert_messages(messages),
            tools=tools,
            **kwargs,
        )
        choice = response.choices[0]
        return Response(
            content=choice.message.content or "",
            model=response.model,
            reasoning_content=self._extract_reasoning(choice.message),
            usage=self._extract_usage(response),
            finish_reason=choice.finish_reason,
            tool_calls=self._extract_tool_calls(choice.message),
        )

    def stream(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Iterator[StreamChunk]:
        reasoning_parts: list[str] = []
        accumulator = _ToolCallAccumulator()
        usage = None
        for chunk in self.client.chat.completions.create(
            model=model,
            messages=self._convert_messages(messages),
            tools=tools,
            stream=True,
            **kwargs,
        ):
            chunk_usage = self._extract_usage(chunk)
            if chunk_usage:
                usage = chunk_usage
            if not chunk.choices:
                continue  # usage-only 末块（choices 为空）——usage 已捕获，流式结束
            choice = chunk.choices[0]
            delta = choice.delta
            accumulator.add(delta)
            if getattr(delta, "reasoning_content", None):
                reasoning_parts.append(delta.reasoning_content)
            if getattr(delta, "content", None):
                yield StreamChunk(content=delta.content, finish_reason=choice.finish_reason)
        tool_calls = accumulator.finish()
        reasoning = "".join(reasoning_parts) if reasoning_parts else None
        if tool_calls or usage or reasoning:
            # 末块补发：完整 reasoning 挂 metadata，tool_calls/usage 对齐 openai
            yield StreamChunk(
                content="",
                tool_calls=tool_calls,
                usage=usage,
                metadata={"reasoning_content": reasoning} if reasoning else None,
            )

    async def achat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Response:
        if self.async_client is None:
            raise RuntimeError("async_client not provided; cannot run async methods")
        response = await self.async_client.chat.completions.create(
            model=model,
            messages=self._convert_messages(messages),
            tools=tools,
            **kwargs,
        )
        choice = response.choices[0]
        return Response(
            content=choice.message.content or "",
            model=response.model,
            reasoning_content=self._extract_reasoning(choice.message),
            usage=self._extract_usage(response),
            finish_reason=choice.finish_reason,
            tool_calls=self._extract_tool_calls(choice.message),
        )

    async def achat_stream(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        if self.async_client is None:
            raise RuntimeError("async_client not provided; cannot run async methods")
        reasoning_parts: list[str] = []
        accumulator = _ToolCallAccumulator()
        usage = None
        stream = await self.async_client.chat.completions.create(
            model=model,
            messages=self._convert_messages(messages),
            tools=tools,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            chunk_usage = self._extract_usage(chunk)
            if chunk_usage:
                usage = chunk_usage
            if not chunk.choices:
                continue  # usage-only 末块（choices 为空）——usage 已捕获，流式结束
            choice = chunk.choices[0]
            delta = choice.delta
            accumulator.add(delta)
            if getattr(delta, "reasoning_content", None):
                reasoning_parts.append(delta.reasoning_content)
            if getattr(delta, "content", None):
                yield StreamChunk(content=delta.content, finish_reason=choice.finish_reason)
        tool_calls = accumulator.finish()
        reasoning = "".join(reasoning_parts) if reasoning_parts else None
        if tool_calls or usage or reasoning:
            yield StreamChunk(
                content="",
                tool_calls=tool_calls,
                usage=usage,
                metadata={"reasoning_content": reasoning} if reasoning else None,
            )
