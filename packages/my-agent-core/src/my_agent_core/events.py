"""事件 dataclass + emit —— Agent 循环的生命周期通知（外部经 on_event 观察）。"""
from collections.abc import Callable
from dataclasses import dataclass

from my_agent_llm import Message


@dataclass(frozen=True)
class Event:
    """事件基类：所有事件都继承它，供 Callable[[Event], None] 类型标注。"""


@dataclass(frozen=True)
class AgentStart(Event):
    """run() 开始。"""


@dataclass(frozen=True)
class TurnStart(Event):
    """一轮 LLM 调用开始。"""

    iteration: int


@dataclass(frozen=True)
class AssistantMessageAdded(Event):
    """助手消息已追加进 messages。"""

    message: Message


@dataclass(frozen=True)
class ToolCallStart(Event):
    """一个工具调用开始。"""

    call_id: str
    name: str
    args: dict


@dataclass(frozen=True)
class ToolCallEnd(Event):
    """一个工具调用结束（含结果文本与是否错误）。"""

    call_id: str
    name: str
    result: str
    is_error: bool


@dataclass(frozen=True)
class AgentEnd(Event):
    """run() 结束。stop_reason: "end_turn" | "max_iterations"。"""

    final_text: str | None
    iterations: int
    stop_reason: str


@dataclass(frozen=True)
class ContextCompacted(Event):
    """context 管理完成一次摘要压缩时发射（context 设计文档，本期只定义不发射）。"""

    tokens_before: int
    tokens_after: int
    summarized_count: int


@dataclass(frozen=True)
class ToolsChanged(Event):
    """工具注册/注销时发射（可扩展性设计文档，本期只定义不发射）。"""

    action: str
    name: str


def emit(callback: Callable[[Event], None] | None, event: Event) -> None:
    """把事件转发给回调；callback 为 None 时为空操作。

    契约：on_event 不应抛异常（抛了会中断循环，视为使用方 bug，不做兜底——
    见框架设计文档 §4.2）。
    """
    if callback is not None:
        callback(event)
