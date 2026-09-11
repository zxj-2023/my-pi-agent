# pyright: reportCallIssue=false
"""Pytest fixtures and universal test doubles for my-agent-core tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from my_agent_llm import Message, Response, StreamChunk

from my_agent_core.tools import tool


class FakeLLM:
    """权威通用测试替身：支持原生流式 achat_stream、非流式 achat、chat 与调用记录。"""

    def __init__(
        self,
        responses: list[Response] | None = None,
        default: Response | None = None,
    ) -> None:
        self.responses: list[Response] = list(responses or [])
        self.default: Response = default or Response(content="ok", model="fake")
        self.calls: list[dict[str, Any]] = []

    def _next_response(self) -> Response:
        if self.responses:
            return self.responses.pop(0)
        return self.default

    def chat(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Response:
        self.calls.append(
            {"messages": list(messages), "tools": tools, "model": model, **kwargs}
        )
        return self._next_response()

    async def achat(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Response:
        return self.chat(messages=messages, tools=tools, model=model, **kwargs)

    async def achat_stream(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append(
            {"messages": list(messages), "tools": tools, "model": model, **kwargs}
        )
        resp = self._next_response()

        if resp.content:
            mid = len(resp.content) // 2
            if mid > 0:
                yield StreamChunk(content=resp.content[:mid])
                yield StreamChunk(
                    content=resp.content[mid:],
                    tool_calls=resp.tool_calls,
                    usage=resp.usage,
                    finish_reason=resp.finish_reason,
                    response=resp,
                )
            else:
                yield StreamChunk(
                    content=resp.content,
                    tool_calls=resp.tool_calls,
                    usage=resp.usage,
                    finish_reason=resp.finish_reason,
                    response=resp,
                )
        elif resp.tool_calls:
            yield StreamChunk(
                content="",
                tool_calls=resp.tool_calls,
                usage=resp.usage,
                finish_reason=resp.finish_reason,
                response=resp,
            )
        else:
            yield StreamChunk(
                content="",
                usage=resp.usage,
                finish_reason=resp.finish_reason or "end_turn",
                response=resp,
            )


def make_response(
    content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
    finish_reason: str | None = None,
) -> Response:
    """构建标准测试 Response。"""
    return Response(
        content=content,
        model="fake",
        tool_calls=tool_calls,
        usage=usage,
        finish_reason=finish_reason or ("tool_use" if tool_calls else "end_turn"),
    )


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool(is_parallel_safe=True)
def get_time() -> str:
    """Get the current time."""
    return "12:00"
