"""OpenAI provider：基准实现，deepseek 以此为模板。"""
from collections.abc import AsyncIterator, Iterator

import openai

from ..config import Config
from ..models import Message, Response, StreamChunk, ToolCall, ToolCallFunction
from ._base import Provider


class _ToolCallAccumulator:
    """聚合流式 tool_calls 增量片段，产出统一形状。

    OpenAI 兼容流式把 tool_call 分片送达：id/name 只出现一次，
    arguments 是碎片 JSON 字符串，按 index 键控拼接。
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict[str, str]] = {}

    def add(self, delta) -> None:
        """消费一个 delta 的 tool_calls 片段。"""
        for tc in getattr(delta, "tool_calls", None) or []:
            index = getattr(tc, "index", 0) or 0
            slot = self._by_index.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if getattr(tc, "id", None):
                slot["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    slot["name"] = fn.name
                if getattr(fn, "arguments", None):
                    slot["arguments"] += fn.arguments

    def finish(self) -> list[dict] | None:
        """流式结束：产出完整 tool_calls（无则 None）。"""
        if not self._by_index:
            return None
        return [
            ToolCall(
                id=slot["id"],
                function=ToolCallFunction(name=slot["name"], arguments=slot["arguments"]),
            ).model_dump()
            for _, slot in sorted(self._by_index.items())
        ]


class OpenAIProvider(Provider):
    """OpenAI provider 实现。"""

    def __init__(self, config: Config, client=None, async_client=None):
        """初始化。client/async_client 可注入（测试缝隙）。"""
        self.config = config
        if client is not None:
            self.client = client
            self.async_client = async_client
            return
        kwargs = {
            "api_key": config.api_key,
            "timeout": config.timeout,
            "max_retries": config.max_retries,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self.client = openai.OpenAI(**kwargs)
        self.async_client = openai.AsyncOpenAI(**kwargs)

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        """Message → OpenAI wire dict。"""
        result = []
        for msg in messages:
            if msg.role == "assistant" and msg.metadata and "tool_calls" in msg.metadata:
                result.append(
                    {
                        "role": "assistant",
                        "content": msg.content or None,
                        "tool_calls": msg.metadata["tool_calls"],
                    }
                )
            elif msg.role == "tool" and msg.metadata:
                result.append(
                    {
                        "role": "tool",
                        "content": msg.content,
                        "tool_call_id": msg.metadata.get("tool_call_id", ""),
                    }
                )
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result

    @staticmethod
    def _extract_tool_calls(message) -> list[dict] | None:
        """从 OpenAI 响应 message 提取 tool_calls（统一形状）。"""
        if not getattr(message, "tool_calls", None):
            return None
        return [
            ToolCall(
                id=tc.id,
                function=ToolCallFunction(name=tc.function.name, arguments=tc.function.arguments),
            ).model_dump()
            for tc in message.tool_calls
        ]

    @staticmethod
    def _extract_usage(response) -> dict[str, int] | None:
        """从响应或流式 chunk 提取 usage。"""
        u = getattr(response, "usage", None)
        if u is None:
            return None
        return {
            "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
            "total_tokens": getattr(u, "total_tokens", 0) or 0,
        }

    def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Response:
        """同步对话。"""
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
        """同步流式：逐 delta 产文本块；流式结束补发末块（完整 tool_calls + usage）。"""
        stream = self.client.chat.completions.create(
            model=model,
            messages=self._convert_messages(messages),
            tools=tools,
            stream=True,
            **kwargs,
        )
        accumulator = _ToolCallAccumulator()
        usage = None
        final_finish_reason: str | None = None
        for chunk in stream:
            chunk_usage = self._extract_usage(chunk)
            if chunk_usage:
                usage = chunk_usage
            if not chunk.choices:
                continue  # usage-only 末块（choices 为空）——usage 已捕获，流式结束
            choice = chunk.choices[0]
            if choice.finish_reason:
                final_finish_reason = choice.finish_reason
            delta = choice.delta
            accumulator.add(delta)
            if getattr(delta, "content", None):
                yield StreamChunk(content=delta.content, finish_reason=choice.finish_reason)
        tool_calls = accumulator.finish()
        if tool_calls or usage:
            yield StreamChunk(content="", tool_calls=tool_calls, usage=usage,
                              finish_reason=final_finish_reason)

    async def achat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Response:
        """异步对话。"""
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
        """异步流式：逐 delta 产文本块；流式结束补发末块（完整 tool_calls + usage）。"""
        if self.async_client is None:
            raise RuntimeError("async_client not provided; cannot run async methods")
        stream = await self.async_client.chat.completions.create(
            model=model,
            messages=self._convert_messages(messages),
            tools=tools,
            stream=True,
            **kwargs,
        )
        accumulator = _ToolCallAccumulator()
        usage = None
        final_finish_reason: str | None = None
        async for chunk in stream:
            chunk_usage = self._extract_usage(chunk)
            if chunk_usage:
                usage = chunk_usage
            if not chunk.choices:
                continue  # usage-only 末块（choices 为空）——usage 已捕获，流式结束
            choice = chunk.choices[0]
            if choice.finish_reason:
                final_finish_reason = choice.finish_reason
            delta = choice.delta
            accumulator.add(delta)
            if getattr(delta, "content", None):
                yield StreamChunk(content=delta.content, finish_reason=choice.finish_reason)
        tool_calls = accumulator.finish()
        if tool_calls or usage:
            yield StreamChunk(content="", tool_calls=tool_calls, usage=usage,
                              finish_reason=final_finish_reason)
