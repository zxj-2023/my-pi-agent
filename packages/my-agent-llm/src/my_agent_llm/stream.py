"""通用流式累加与规范化器（对标 Tau stream.py 与 canonicalize_provider_stream）。

统一在模型层维护 partial: Message，消化 Token 累加、首字启动、工具拼装、取消与异常包装。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .events import (
    StreamDoneEvent,
    StreamErrorEvent,
    StreamEvent,
    StreamStartEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallDoneEvent,
)
from .models import Message, Response, StreamChunk, ToolCall

__all__ = ["StreamAccumulator"]


class StreamAccumulator:
    """流式累加器：维护单次请求的流式累加状态并输出高阶事件。"""

    def __init__(self, role: str = "assistant") -> None:
        self.role = role
        self.content: str = ""
        self.metadata: dict[str, Any] = {}
        self.started: bool = False
        self.tool_calls: list[ToolCall] = []
        self.last_usage: dict[str, int] | None = None
        self.final_response: Response | None = None

    def _snapshot(self) -> Message:
        meta = dict(self.metadata) if self.metadata else {}
        if self.tool_calls:
            meta["tool_calls"] = [
                tc.model_dump() if hasattr(tc, "model_dump") else tc
                for tc in self.tool_calls
            ]
        return Message(
            role=self.role,
            content=self.content,
            metadata=meta if meta else None,
        )

    def feed(self, chunk: Any) -> list[StreamEvent]:
        """消化单个底层 StreamChunk / Response 并产出对应的上层高阶事件。"""
        events: list[StreamEvent] = []

        if not self.started:
            self.started = True
            events.append(StreamStartEvent(partial=self._snapshot()))

        # 1. 思考链增量 (Reasoning / Thinking)
        meta = getattr(chunk, "metadata", None)
        reasoning_delta: str | None = None
        if isinstance(meta, dict) and "reasoning_content" in meta:
            reasoning_delta = meta["reasoning_content"]
        elif getattr(chunk, "reasoning_content", None):
            reasoning_delta = chunk.reasoning_content

        if reasoning_delta:
            prev_reasoning = str(self.metadata.get("reasoning_content", ""))
            self.metadata["reasoning_content"] = prev_reasoning + reasoning_delta
            events.append(
                ThinkingDeltaEvent(delta=reasoning_delta, partial=self._snapshot())
            )

        # 2. 正文文本增量 (Text Delta)
        content = getattr(chunk, "content", "") or ""
        if content:
            self.content += content
            events.append(TextDeltaEvent(delta=content, partial=self._snapshot()))

        # 3. 工具调用增量 (Tool Calls)
        tool_calls = getattr(chunk, "tool_calls", None)
        if tool_calls:
            self.tool_calls = []
            for idx, tc in enumerate(tool_calls):
                if isinstance(tc, dict):
                    tc_obj = ToolCall.model_validate(tc)
                else:
                    tc_obj = tc
                self.tool_calls.append(tc_obj)
                events.append(
                    ToolCallDoneEvent(
                        index=idx,
                        tool_call=tc_obj,
                        partial=self._snapshot(),
                    )
                )

        # 4. Usage 统计
        usage = getattr(chunk, "usage", None)
        if isinstance(usage, dict):
            self.last_usage = usage
            self.metadata["usage"] = usage

        # 5. 终态已拼装好的 Response 实体
        resp = getattr(chunk, "response", None)
        if resp is not None and isinstance(resp, Response):
            self.final_response = resp
        elif isinstance(chunk, Response):
            self.final_response = chunk

        return events

    def finish(self, stop_reason: str = "stop") -> StreamDoneEvent:
        """完成流式会话，交付最终完型的 Message 与 Usage。"""
        if not self.started:
            self.started = True

        if self.final_response is not None and hasattr(
            self.final_response, "to_message"
        ):
            msg = self.final_response.to_message(
                role=self.role, stop_reason=stop_reason
            )
            usage = self.last_usage or getattr(self.final_response, "usage", None)
        else:
            meta = dict(self.metadata) if self.metadata else {}
            if self.tool_calls:
                meta["tool_calls"] = [
                    tc.model_dump() if hasattr(tc, "model_dump") else tc
                    for tc in self.tool_calls
                ]
            if stop_reason:
                meta["stop_reason"] = stop_reason
            msg = Message(
                role=self.role,
                content=self.content,
                metadata=meta if meta else None,
            )
            usage = self.last_usage

        return StreamDoneEvent(message=msg, usage=usage)

    def fail(
        self,
        exc: Exception | None = None,
        cancelled: bool = False,
    ) -> StreamErrorEvent:
        """遇到取消或异常时，构建安全的终态错误 Message（Never-Throw 保证）。"""
        stop_reason = "cancelled" if cancelled else "error"
        content = self.content
        if exc is not None:
            err_str = str(exc)
            content = (
                f"{content} (Error during model stream: {err_str})"
                if content
                else err_str
            )

        meta = dict(self.metadata) if self.metadata else {}
        if self.tool_calls:
            meta["tool_calls"] = [
                tc.model_dump() if hasattr(tc, "model_dump") else tc
                for tc in self.tool_calls
            ]
        meta["stop_reason"] = stop_reason

        error_msg = Message(
            role=self.role,
            content=content,
            metadata=meta if meta else None,
        )
        return StreamErrorEvent(error=error_msg, stop_reason=stop_reason, exc=exc)

    async def stream(
        self,
        source: AsyncIterator[StreamChunk],
        signal: Any | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """全生命周期异步生成器：将底层 StreamChunk 转换为高阶 StreamEvent。"""
        cancelled = False
        error_exc: Exception | None = None

        def is_cancelled() -> bool:
            if signal is None:
                return False
            check = getattr(signal, "is_cancelled", None)
            if callable(check):
                return bool(check())
            return bool(getattr(signal, "cancelled", False))

        try:
            if is_cancelled():
                cancelled = True
            else:
                async for chunk in source:
                    for ev in self.feed(chunk):
                        yield ev

                    if is_cancelled():
                        cancelled = True
                        break
        except Exception as exc:
            if is_cancelled():
                cancelled = True
            else:
                error_exc = exc

        if not self.started:
            self.started = True
            yield StreamStartEvent(partial=self._snapshot())

        if cancelled or error_exc is not None:
            yield self.fail(exc=error_exc, cancelled=cancelled)
        else:
            yield self.finish()
