"""事件 dataclass —— Agent 循环生命周期纯只读事实广播通知（对齐 Pi 架构）。

所有的 Event 均为不可变 (frozen) 事实数据结构，自动带 timestamp，单向向外广播，绝不包含控制拦截逻辑。
控制流拦截与参数改写已正交解耦至 hooks.py。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from my_agent_llm import Message, StreamChunk  # pyright: ignore[reportMissingImports]

__all__ = [
    "Event",
    "AgentStart",
    "AgentEnd",
    "TurnStart",
    "TurnEnd",
    "MessageStart",
    "MessageUpdate",
    "MessageEnd",
    "ToolExecutionStart",
    "ToolExecutionUpdate",
    "ToolExecutionEnd",
    "ContextCompacted",
    "ToolsChanged",
]


# ── 纯只读生命周期事实事件基类
@dataclass(frozen=True)
class Event:
    """生命周期事实事件基类（纯只读广播，不可变）。

    自动带 timestamp（Unix 秒，实例化时刻）。
    使用 field(init=False) + __post_init__ 注入，避免子类非默认字段顺序限制，并暴露类型。
    """

    timestamp: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", time.time())


# ── Agent 宏观生命周期事件
@dataclass(frozen=True)
class AgentStart(Event):
    """Agent 全流程开始通知。"""

    system_prompt: str = ""
    user_input: str = ""


@dataclass(frozen=True)
class AgentEnd(Event):
    """Agent 全流程结束通知。"""

    messages: list[Message]
    final_text: str | None
    iterations: int
    stop_reason: (
        str  # "end_turn" | "max_iterations" | "cancelled" | "blocked" | "error"
    )


# ── Turn 微观轮次生命周期事件
@dataclass(frozen=True)
class TurnStart(Event):
    """单轮推理迭代开始通知。"""

    iteration: int


@dataclass(frozen=True)
class TurnEnd(Event):
    """单轮推理迭代结束通知（严格保证成对闭合）。"""

    message: Message | None = None
    tool_results: list[Message] = field(default_factory=list)


# ── 消息流生命周期事件
@dataclass(frozen=True)
class MessageStart(Event):
    """消息加入对话流通知。"""

    message: Message


@dataclass(frozen=True)
class MessageUpdate(Event):
    """流式 Token 增量更新通知（打字机专用）。"""

    message: Message
    chunk: StreamChunk | None = None


@dataclass(frozen=True)
class MessageEnd(Event):
    """消息完整落地通知。"""

    message: Message


# ── 工具执行事实生命周期事件
@dataclass(frozen=True)
class ToolExecutionStart(Event):
    """工具开始执行通知（Preflight 阶段按 source order 发射）。"""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolExecutionUpdate(Event):
    """工具流式进度更新通知。"""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    partial_result: Any


@dataclass(frozen=True)
class ToolExecutionEnd(Event):
    """工具执行完毕通知（Completion 阶段按完成顺序发射）。"""

    tool_call_id: str
    tool_name: str
    result: str
    is_error: bool


# ── 系统内部状态事件
@dataclass(frozen=True)
class ContextCompacted(Event):
    """上下文压缩事件通知。"""

    tokens_before: int
    tokens_after: int
    summarized_count: int


@dataclass(frozen=True)
class ToolsChanged(Event):
    """工具注册/注销通知。"""

    action: str
    name: str
