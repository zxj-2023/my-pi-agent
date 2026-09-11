"""模型边界层高阶流式事件模型（对标 Tau provider_events）。

提供供应商中立的高阶流式生命周期事件，携带实时累积的 partial: Message 快照。
"""

from __future__ import annotations

from dataclasses import dataclass

from my_agent_llm.models import Message, ToolCall

__all__ = [
    "StreamDoneEvent",
    "StreamErrorEvent",
    "StreamEvent",
    "StreamStartEvent",
    "TextDeltaEvent",
    "ThinkingDeltaEvent",
    "ToolCallDeltaEvent",
    "ToolCallDoneEvent",
]


@dataclass(frozen=True)
class StreamEvent:
    """高阶流式事件基类。"""


@dataclass(frozen=True)
class StreamStartEvent(StreamEvent):
    """首个 Token 生成时发射，携带初始 partial Message 快照。"""

    partial: Message


@dataclass(frozen=True)
class TextDeltaEvent(StreamEvent):
    """正文文本增量事件。"""

    delta: str
    partial: Message


@dataclass(frozen=True)
class ThinkingDeltaEvent(StreamEvent):
    """思维链推理增量事件（对标 DeepSeek-R1 / Claude 3.7 Thinking）。"""

    delta: str
    partial: Message


@dataclass(frozen=True)
class ToolCallDeltaEvent(StreamEvent):
    """工具参数增量事件。"""

    index: int
    delta: str
    partial: Message


@dataclass(frozen=True)
class ToolCallDoneEvent(StreamEvent):
    """单个工具调用参数组装完毕事件。"""

    index: int
    tool_call: ToolCall
    partial: Message


@dataclass(frozen=True)
class StreamDoneEvent(StreamEvent):
    """流式正常结束事件，携带完整完型的 Message 实体与 Usage。"""

    message: Message
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class StreamErrorEvent(StreamEvent):
    """流式异常或中途取消事件（Never-Throw 保证）。"""

    error: Message
    stop_reason: str = "error"  # "error" | "cancelled"
    exc: Exception | None = None
