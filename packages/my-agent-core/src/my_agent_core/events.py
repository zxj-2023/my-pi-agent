"""事件 dataclass —— Agent 循环的生命周期通知（外部经 on_event 观察）。"""
from dataclasses import dataclass

from my_agent_llm import Message


@dataclass(frozen=True)
class Event:
    """事件基类：仅用于类型标注 Callable[[Event], None]。"""


@dataclass(frozen=True)
class AgentStart:
    """run() 开始。"""


@dataclass(frozen=True)
class TurnStart:
    """一轮 LLM 调用开始。"""

    iteration: int


@dataclass(frozen=True)
class AssistantMessageAdded:
    """助手消息已追加进 messages。"""

    message: Message


@dataclass(frozen=True)
class ToolCallStart:
    """一个工具调用开始。"""

    call_id: str
    name: str
    args: dict


@dataclass(frozen=True)
class ToolCallEnd:
    """一个工具调用结束（含结果文本与是否错误）。"""

    call_id: str
    name: str
    result: str
    is_error: bool


@dataclass(frozen=True)
class AgentEnd:
    """run() 结束。stop_reason: "end_turn" | "max_iterations"。"""

    final_text: str | None
    iterations: int
    stop_reason: str


@dataclass(frozen=True)
class ContextCompacted:
    """context 管理完成一次摘要压缩时发射（context 设计文档，本期只定义不发射）。"""

    tokens_before: int
    tokens_after: int
    summarized_count: int


@dataclass(frozen=True)
class ToolsChanged:
    """工具注册/注销时发射（可扩展性设计文档，本期只定义不发射）。"""

    action: str
    name: str
