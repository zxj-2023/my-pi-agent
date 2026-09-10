"""事件 dataclass 与专职决策拦截点契约 —— Agent 循环生命周期只读广播与拦截干预。

架构设计（对齐 Pi 架构）：
1. 纯只读事实流（Event / AgentEvent）：单向广播，不可变 (frozen)，带 timestamp，绝无 Interceptable 标记或返回值。
2. 五大独立决策拦截点契约（DecisionPoint）：独立于 Event，专职控制流拦截与参数改写。
3. DecisionRegistry（别名 HookRegistry）：负责决策点的注册、注销、async/sync 混合调用及 Never-Throw 异常捕获隔离。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from my_agent_llm import Message, StreamChunk  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


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
    stop_reason: str  # "end_turn" | "max_iterations" | "cancelled" | "blocked"


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


AgentEvent = Event


# ── 五大专职决策拦截点契约（独立门禁系统，非 Event）
@dataclass(frozen=True)
class UserInputDecision:
    """决策点 1 (input): 拦截或改写用户原始输入文本。"""

    input_text: str


@dataclass(frozen=True)
class AgentStartDecision:
    """决策点 2 (before_agent_start): 拦截启动或动态重写 system_prompt。"""

    system_prompt: str


@dataclass(frozen=True)
class BeforeModelCallDecision:
    """决策点 3 (context): 调模型前 1ms 审查或临时改写发送视图。"""

    messages: list[Message]
    iteration: int


@dataclass(frozen=True)
class ToolCallDecision:
    """决策点 4 (tool_call): 工具执行前安全审批、阻断高危命令或改写入参。"""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResultDecision:
    """决策点 5 (tool_result): 工具执行后改写返回内容或篡改报错状态。"""

    tool_call_id: str
    tool_name: str
    result: str
    is_error: bool


# 过渡兼容别名（支撑尚未重构的 agent.py 与 loop.py 运行）
UserInput = UserInputDecision
BeforeModelCall = BeforeModelCallDecision


@dataclass(frozen=True)
class HookResult:
    """决策拦截点的统一干预结果。返回 None = 纯观察，返回 HookResult = 干预。

    - UserInputDecision 用 block / reason / updated_input（拦截 / 改写用户输入）
    - AgentStartDecision 用 block / reason / updated_system_prompt（拦截 / 改写 system prompt）
    - BeforeModelCallDecision 用 block / reason / updated_messages（拦截 / 临时改写送给 LLM 的 messages 视图）
    - ToolCallDecision 用 block / reason / updated_args（拦截 / 改参数）
    - ToolResultDecision 用 updated_result（改结果）
    """

    block: bool = False
    reason: str | None = None
    updated_input: str | None = None
    updated_system_prompt: str | None = None
    updated_messages: list[Message] | None = None
    updated_args: dict[str, Any] | None = None
    updated_result: str | None = None


class DecisionRegistry:
    """决策拦截点注册表：决策点类型 → callback 列表。

    支持 async / sync 钩子混合执行与 Never-Throw 异常捕获隔离。
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[..., Any]]] = {}
        self._hooks = self._handlers

    def register(self, decision_cls: type, callback: Callable[..., Any]) -> None:
        """挂一个决策回调到决策点类型。同一决策点可挂多个，按注册顺序触发。"""
        self._handlers.setdefault(decision_cls, []).append(callback)

    def unregister(self, decision_cls: type, callback: Callable[..., Any]) -> None:
        """移除决策回调。"""
        with contextlib.suppress(ValueError):
            self._handlers.get(decision_cls, []).remove(callback)

    async def emit(self, decision: Any) -> HookResult | None:
        """异步触发决策点的所有回调，支持协程与普通函数。

        - 返回第一个非 None 结果（短路）。
        - 坚守 Never-Throw 保证：若回调执行抛出异常，捕获并记录日志，绝不向外抛出异常，继续执行后续回调。
        """
        for cb in list(self._handlers.get(type(decision), [])):
            try:
                if asyncio.iscoroutinefunction(cb):
                    result = await cb(decision)
                else:
                    result = cb(decision)
                    if inspect.isawaitable(result):
                        result = await result
                if result is not None:
                    return result
            except Exception as e:
                logger.error(
                    "Decision callback %r failed on %r: %s",
                    cb,
                    decision,
                    e,
                    exc_info=True,
                )
        return None


HookRegistry = DecisionRegistry
