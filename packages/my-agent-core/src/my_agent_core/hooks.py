"""专职 Hook 拦截点契约与 HookRegistry —— Agent 关键节点双向拦截干预与控制流门禁。

架构设计（对齐 Pi 架构）：
1. 专职 Hook 拦截点契约（*Hook）：独立于 Event，专职控制流拦截、入参安全审批与出参改写。
2. 统一干预结果模型（HookResult）：携带 block、reason、updated_* 属性，指示核心状态机如何处置。
3. HookRegistry：负责拦截钩子的注册、注销、async/sync 混合调用及严格的 Never-Throw 异常隔离。
"""

from __future__ import annotations

import contextlib
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from my_agent_llm import Message  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


# ── 五大专职 Hook 拦截点契约（独立门禁系统，非 Event）
@dataclass(frozen=True)
class UserInputHook:
    """Hook 1 (input): 拦截或改写用户原始输入文本。"""

    input_text: str


@dataclass(frozen=True)
class AgentStartHook:
    """Hook 2 (before_agent_start): 拦截启动或动态重写 system_prompt。"""

    system_prompt: str


@dataclass(frozen=True)
class BeforeModelCallHook:
    """Hook 3 (context): 调模型前 1ms 审查或临时改写发送视图。"""

    messages: list[Message]
    iteration: int


@dataclass(frozen=True)
class ToolCallHook:
    """Hook 4 (tool_call): 工具执行前安全审批、阻断高危命令或改写入参。"""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResultHook:
    """Hook 5 (tool_result): 工具执行后改写返回内容或篡改报错状态。"""

    tool_call_id: str
    tool_name: str
    result: str
    is_error: bool
    terminate: bool = False


@dataclass(frozen=True)
class HookResult:
    """Hook 拦截点的统一干预结果。返回 None = 纯观察，返回 HookResult = 干预。

    - UserInputHook 用 block / reason / updated_input（拦截 / 改写用户输入）
    - AgentStartHook 用 block / reason / updated_system_prompt（拦截 / 改写 system prompt）
    - BeforeModelCallHook 用 block / reason / updated_messages（拦截 / 临时改写送给 LLM 的 messages 视图）
    - ToolCallHook 用 block / reason / updated_args（拦截 / 改参数）
    - ToolResultHook 用 updated_result（改结果）
    """

    block: bool = False
    reason: str | None = None
    updated_input: str | None = None
    updated_system_prompt: str | None = None
    updated_messages: list[Message] | None = None
    updated_args: dict[str, Any] | None = None
    updated_result: str | None = None
    terminate: bool | None = None


class HookRegistry:
    """Hook 注册表：Hook 类型 → callback 列表。

    支持 async / sync 钩子混合执行与 Never-Throw 异常捕获隔离。
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[..., Any]]] = {}
        self._hooks = self._handlers

    def register(self, hook_cls: type, callback: Callable[..., Any]) -> None:
        """挂一个 hook 回调到 hook 类型。同一 hook 可挂多个，按注册顺序触发。"""
        self._handlers.setdefault(hook_cls, []).append(callback)

    def unregister(self, hook_cls: type, callback: Callable[..., Any]) -> None:
        """移除 hook 回调。"""
        with contextlib.suppress(ValueError):
            self._handlers.get(hook_cls, []).remove(callback)

    async def emit(self, hook_payload: Any) -> HookResult | None:
        """异步触发 hook 的所有回调，支持协程与普通函数。

        - 返回第一个非 None 结果（短路）。
        - 坚守 Never-Throw 保证：若回调执行抛出异常，捕获并记录日志，绝不向外抛出异常，继续执行后续回调。
        """
        for cb in list(self._handlers.get(type(hook_payload), [])):
            try:
                if inspect.iscoroutinefunction(cb):
                    result = await cb(hook_payload)
                else:
                    result = cb(hook_payload)
                    if inspect.isawaitable(result):
                        result = await result
                if result is not None:
                    return result
            except Exception as e:
                logger.error(
                    "Hook callback %r failed on %r: %s",
                    cb,
                    hook_payload,
                    e,
                    exc_info=True,
                )
        return None
