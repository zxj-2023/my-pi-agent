"""OpenAI provider：基准实现，deepseek 以此为模板。"""
from collections.abc import AsyncIterator, Iterator

import openai

from ..config import Config
from ..models import Message, Response, StreamChunk
from ._base import Provider


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
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]

    @staticmethod
    def _extract_usage(response) -> dict[str, int] | None:
        """从响应提取 usage。"""
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
        """同步流式：逐 delta 产文本块；v1 简化：末块 tool_calls/usage 由调用方自行汇总。"""
        stream = self.client.chat.completions.create(
            model=model,
            messages=self._convert_messages(messages),
            tools=tools,
            stream=True,
            **kwargs,
        )
        for chunk in stream:
            if not chunk.choices:
                continue  # usage-only 末块（choices 为空）——跳过，流式结束
            choice = chunk.choices[0]
            delta = choice.delta
            if getattr(delta, "content", None):
                yield StreamChunk(content=delta.content, finish_reason=choice.finish_reason)
        # 流式结束：tool_calls/usage 由 SDK 累加在最终对象，此处从简——末块由调用方自行汇总
        # （实现时若需 tool_calls，参考 pig-mono 的 astream_openai_tool_aware；v1 简化）

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
        """异步流式。"""
        if self.async_client is None:
            raise RuntimeError("async_client not provided; cannot run async methods")
        stream = await self.async_client.chat.completions.create(
            model=model,
            messages=self._convert_messages(messages),
            tools=tools,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue  # usage-only 末块（choices 为空）——跳过，流式结束
            choice = chunk.choices[0]
            delta = choice.delta
            if getattr(delta, "content", None):
                yield StreamChunk(content=delta.content, finish_reason=choice.finish_reason)
