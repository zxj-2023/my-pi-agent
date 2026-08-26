"""事件 dataclass + HookResult —— Agent 循环的生命周期通知（外部经 hook 观察/干预）。

事件集对齐 pi 的生命周期模型（Agent/Turn/Message/Tool 四组；正常执行 start/end
成对，被拦截/畸形参数的调用不发射 End）。
MessageUpdate / ToolExecutionUpdate 为异步流式发射。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from my_agent_llm import Message  # pyright: ignore[reportMissingImports]


@dataclass(frozen=True)
class Event:
    """事件基类：所有事件都继承它，供 Callable[[Event], None] 类型标注。

    自动带 timestamp（Unix 秒，实例化时刻）。用 __post_init__ + object.__setattr__
    注入而非 dataclass 字段——避免「基类默认字段在子类非默认字段前」的顺序限制。
    """

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", time.time())


class Interceptable:
    """标记：该事件可被 hook 干预（回调返回值生效）。"""


# ── 用户输入到达（进入 Session 和消息历史前）
@dataclass(frozen=True)
class UserInput(Event, Interceptable):
    """用户原始输入到达（在进入 Session 和消息历史之前触发，可被拦截或改写）。"""

    input_text: str


# ── Agent 生命周期
@dataclass(frozen=True)
class AgentStart(Event, Interceptable):
    """run() 开始（可被 hook 拦截/改写 system prompt）。"""

    system_prompt: str = ""
    user_input: str = ""


@dataclass(frozen=True)
class AgentEnd(Event):
    """run() 结束。stop_reason: "end_turn" | "max_iterations" | "cancelled"。"""

    messages: list[Message]
    final_text: str | None
    iterations: int
    stop_reason: str


# ── Turn 生命周期（一轮 = 一次助手响应 + 工具调用/结果）
@dataclass(frozen=True)
class TurnStart(Event):
    """一轮 LLM 调用开始。"""

    iteration: int


@dataclass(frozen=True)
class BeforeModelCall(Event, Interceptable):
    """每次调用 LLM 前触发（携带已完成压缩的当前上下文 view 副本，可临时注入/过滤消息）。"""

    messages: list[Message]
    iteration: int


@dataclass(frozen=True)
class TurnEnd(Event):
    """一轮结束：携带该轮助手消息与工具结果消息。"""

    message: Message
    tool_results: list[Message]


# ── 消息生命周期（user / assistant / tool 消息都会发）
@dataclass(frozen=True)
class MessageStart(Event):
    """一条消息开始进入 transcript。"""

    message: Message


@dataclass(frozen=True)
class MessageUpdate(Event, Interceptable):
    """消息增量更新（异步流式发射，每收到一个 Token 时触发；支持被 Hook 拦截取消）。"""

    message: Message
    chunk: Any = None


@dataclass(frozen=True)
class MessageEnd(Event):
    """一条消息完整进入 transcript。"""

    message: Message


# ── 工具执行生命周期
@dataclass(frozen=True)
class ToolExecutionStart(Event, Interceptable):
    """一个工具调用开始（可被 hook 拦截/改参数）。"""

    tool_call_id: str
    tool_name: str
    args: dict


@dataclass(frozen=True)
class ToolExecutionUpdate(Event):
    """工具结果增量更新（仅异步流式发射）。"""

    tool_call_id: str
    tool_name: str
    args: dict
    partial_result: Any


@dataclass(frozen=True)
class ToolExecutionEnd(Event, Interceptable):
    """一个工具调用结束（可被 hook 改结果）。"""

    tool_call_id: str
    tool_name: str
    result: str
    is_error: bool


# ── 预留（后续阶段）
@dataclass(frozen=True)
class ContextCompacted(Event):
    """context 管理完成一次摘要压缩时发射（context 设计文档 §4.3）。"""

    tokens_before: int
    tokens_after: int
    summarized_count: int


@dataclass(frozen=True)
class ToolsChanged(Event):
    """工具注册/注销时发射（可扩展性设计文档，本期只定义不发射）。"""

    action: str
    name: str


@dataclass(frozen=True)
class HookResult:
    """hook 回调的干预结果。返回 None = 纯观察，返回 HookResult = 干预。

    - UserInput 用 block / reason / updated_input（拦截 / 改写用户输入）
    - AgentStart 用 block / reason / updated_system_prompt（拦截 / 改写 system prompt）
    - BeforeModelCall 用 block / reason / updated_messages（拦截 / 临时改写送给 LLM 的 messages 视图）
    - ToolExecutionStart 用 block / reason / updated_args（拦截 / 改参数）
    - ToolExecutionEnd 用 updated_result（改结果）
    - MessageUpdate 用 block / reason（中途中止流式生成并丢弃半截产物）
    """

    block: bool = False
    reason: str | None = None
    updated_input: str | None = None
    updated_system_prompt: str | None = None
    updated_messages: list[Message] | None = None
    updated_args: dict | None = None
    updated_result: str | None = None


class HookRegistry:
    """hook 注册表（对标 ToolRegistry）：事件类型 → callback 列表。支持 async / sync 钩子混合执行。"""

    def __init__(self):
        self._hooks: dict[type[Event], list[Callable]] = {}

    def register(self, event_cls: type[Event], callback: Callable) -> None:
        """挂一个 hook 到事件类。同一事件可挂多个，按注册顺序触发。"""
        self._hooks.setdefault(event_cls, []).append(callback)

    def unregister(self, event_cls: type[Event], callback: Callable) -> None:
        """移除 hook。"""
        with contextlib.suppress(ValueError):
            self._hooks.get(event_cls, []).remove(callback)

    async def emit(self, event: Event) -> HookResult | None:
        """异步触发事件的所有 hook，支持协程与普通函数，返回第一个非 None 结果（短路）。"""
        for cb in self._hooks.get(type(event), []):
            if asyncio.iscoroutinefunction(cb):
                result = await cb(event)
            else:
                result = cb(event)
            if result is not None:
                return result
        return None
