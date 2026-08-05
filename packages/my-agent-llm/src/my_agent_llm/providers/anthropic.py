"""Anthropic provider：block 双向翻译 + 原生 web_search 增强。"""
import json
from collections.abc import AsyncIterator, Iterator

import anthropic

from ..config import Config
from ..models import Message, Response, StreamChunk
from ._base import Provider


class AnthropicProvider(Provider):
    """Anthropic (Claude) provider 实现。"""

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
        self.client = anthropic.Anthropic(**kwargs)
        self.async_client = anthropic.AsyncAnthropic(**kwargs)

    def _convert_messages(self, messages: list[Message]) -> tuple[str | None, list[dict]]:
        """Message → Anthropic 格式。返回 (system, messages)。"""
        system_message = None
        anthropic_messages = []
        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            elif msg.role == "assistant" and msg.metadata and "tool_calls" in msg.metadata:
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.metadata["tool_calls"]:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": json.loads(tc["function"]["arguments"]),
                        }
                    )
                anthropic_messages.append({"role": "assistant", "content": content})
            elif msg.role == "tool" and msg.metadata:
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.metadata.get("tool_call_id"),
                                "content": msg.content,
                            }
                        ],
                    }
                )
            else:
                anthropic_messages.append({"role": msg.role, "content": msg.content})
        return system_message, anthropic_messages

    def _convert_tools(self, tools: list[dict] | None) -> list[dict] | None:
        """OpenAI 形状 tools → Anthropic 格式。"""
        if not tools:
            return None
        out = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                out.append(
                    {
                        "name": func["name"],
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {}),
                    }
                )
        return out or None

    def _resolve_tools(self, tools, kwargs) -> list[dict] | None:
        """function tools + 可选原生 web_search。"""
        enable_web = kwargs.pop("enable_web_search", False)
        max_uses = kwargs.pop("web_search_max_uses", 5)
        out = self._convert_tools(tools) or []
        if enable_web:
            out = list(out)
            out.append({"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses})
        return out or None

    @staticmethod
    def _extract_content(blocks) -> str:
        """text blocks → content。"""
        return "".join(b.text for b in blocks if getattr(b, "type", None) == "text")

    @staticmethod
    def _extract_reasoning(blocks) -> str | None:
        """thinking blocks → reasoning_content。"""
        parts = [b.thinking for b in blocks if getattr(b, "type", None) == "thinking" and getattr(b, "thinking", None)]
        return "".join(parts) or None

    @staticmethod
    def _extract_tool_calls(blocks) -> list[dict] | None:
        """tool_use blocks → OpenAI 形状 tool_calls。"""
        out = []
        for block in blocks:
            if getattr(block, "type", None) == "tool_use":
                out.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {"name": block.name, "arguments": json.dumps(block.input)},
                    }
                )
        return out or None

    @staticmethod
    def _extract_usage(response) -> dict[str, int] | None:
        """usage → OpenAI 形状。"""
        u = getattr(response, "usage", None)
        if u is None:
            return None
        in_t = int(getattr(u, "input_tokens", 0) or 0)
        out_t = int(getattr(u, "output_tokens", 0) or 0)
        return {"prompt_tokens": in_t, "completion_tokens": out_t, "total_tokens": in_t + out_t}

    def chat(self, messages, *, model, tools=None, **kwargs) -> Response:
        system, ant_messages = self._convert_messages(messages)
        ant_tools = self._resolve_tools(tools, kwargs)
        kwargs.pop("tools", None)
        response = self.client.messages.create(
            model=model,
            messages=ant_messages,
            system=system,
            max_tokens=kwargs.pop("max_tokens", 4096),
            **({"tools": ant_tools} if ant_tools else {}),
            **kwargs,
        )
        return Response(
            content=self._extract_content(response.content),
            model=response.model,
            reasoning_content=self._extract_reasoning(response.content),
            usage=self._extract_usage(response),
            finish_reason=response.stop_reason,
            tool_calls=self._extract_tool_calls(response.content),
        )

    def stream(self, messages, *, model, tools=None, **kwargs) -> Iterator[StreamChunk]:
        system, ant_messages = self._convert_messages(messages)
        ant_tools = self._resolve_tools(tools, kwargs)
        kwargs.pop("tools", None)
        with self.client.messages.stream(
            model=model,
            messages=ant_messages,
            system=system,
            max_tokens=kwargs.pop("max_tokens", 4096),
            **({"tools": ant_tools} if ant_tools else {}),
            **kwargs,
        ) as stream:
            for text in stream.text_stream:
                yield StreamChunk(content=text, finish_reason=None)
            final = stream.get_final_message()
            tool_calls = self._extract_tool_calls(final.content)
            reasoning = self._extract_reasoning(final.content)
            usage = self._extract_usage(final)
            if tool_calls or reasoning or usage:
                yield StreamChunk(
                    content="",
                    tool_calls=tool_calls,
                    usage=usage,
                    finish_reason=final.stop_reason,
                    metadata={"reasoning_content": reasoning} if reasoning else None,
                )

    async def achat(self, messages, *, model, tools=None, **kwargs) -> Response:
        if self.async_client is None:
            raise RuntimeError("async_client not provided; cannot run async methods")
        system, ant_messages = self._convert_messages(messages)
        ant_tools = self._resolve_tools(tools, kwargs)
        kwargs.pop("tools", None)
        response = await self.async_client.messages.create(
            model=model,
            messages=ant_messages,
            system=system,
            max_tokens=kwargs.pop("max_tokens", 4096),
            **({"tools": ant_tools} if ant_tools else {}),
            **kwargs,
        )
        return Response(
            content=self._extract_content(response.content),
            model=response.model,
            reasoning_content=self._extract_reasoning(response.content),
            usage=self._extract_usage(response),
            finish_reason=response.stop_reason,
            tool_calls=self._extract_tool_calls(response.content),
        )

    async def achat_stream(self, messages, *, model, tools=None, **kwargs) -> AsyncIterator[StreamChunk]:
        if self.async_client is None:
            raise RuntimeError("async_client not provided; cannot run async methods")
        system, ant_messages = self._convert_messages(messages)
        ant_tools = self._resolve_tools(tools, kwargs)
        kwargs.pop("tools", None)
        async with self.async_client.messages.stream(
            model=model,
            messages=ant_messages,
            system=system,
            max_tokens=kwargs.pop("max_tokens", 4096),
            **({"tools": ant_tools} if ant_tools else {}),
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                yield StreamChunk(content=text, finish_reason=None)
            final = await stream.get_final_message()
            tool_calls = self._extract_tool_calls(final.content)
            reasoning = self._extract_reasoning(final.content)
            usage = self._extract_usage(final)
            if tool_calls or reasoning or usage:
                yield StreamChunk(
                    content="",
                    tool_calls=tool_calls,
                    usage=usage,
                    finish_reason=final.stop_reason,
                    metadata={"reasoning_content": reasoning} if reasoning else None,
                )
