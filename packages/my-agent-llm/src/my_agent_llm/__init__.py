"""统一 LLM 客户端包（模型边界层）。"""

from .client import LLM
from .config import Config
from .events import (  # pyright: ignore[reportMissingImports]
    StreamDoneEvent,
    StreamErrorEvent,
    StreamEvent,
    StreamStartEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallDeltaEvent,
    ToolCallDoneEvent,
)
from .models import (
    Message,
    Response,
    StreamChunk,
    ToolCall,
    TurnOutcome,
    normalize_finish_reason,
)
from .providers import Provider
from .stream import StreamAccumulator  # pyright: ignore[reportMissingImports]

__all__ = [
    "LLM",
    "Config",
    "Message",
    "Response",
    "StreamAccumulator",
    "StreamChunk",
    "StreamDoneEvent",
    "StreamErrorEvent",
    "StreamEvent",
    "StreamStartEvent",
    "TextDeltaEvent",
    "ThinkingDeltaEvent",
    "ToolCallDeltaEvent",
    "ToolCallDoneEvent",
    "ToolCall",
    "TurnOutcome",
    "normalize_finish_reason",
    "Provider",
]
