"""单层 Agent —— 状态 + 循环 + 工具执行全在一个类（pig-mono 式）。

模型调用 → 检查 tool_calls → 执行工具 → 观察结果写回消息 → 循环，
直到模型不再发起工具调用（经典退出条件：tool_calls 为空 → 结束）。

模型边界交给 my-agent-llm 的 LLM 门面；消息状态是 Message 对象列表。
"""
from __future__ import annotations

import json
from typing import Callable

from my_agent_llm import LLM, Message

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    Event,
    HookResult,
    Interceptable,
    MessageEnd,
    MessageStart,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
)
from my_agent_core.registry import ToolRegistry
from my_agent_core.tools import Tool, ToolResult


class Agent:
    """单层 Agent：持有 llm / 工具注册表 / 消息，内联 ReAct 循环。"""

    def __init__(self, *, llm: LLM, tools: list[Tool], system_prompt: str | None = None,
                 max_iterations: int | None = None):
        """各参数语义见框架设计文档 §4.3（hook 通过 register_hook 挂载）。"""
        self.llm = llm
        self.registry = ToolRegistry()
        for t in tools:
            self.registry.register(t)
        self.messages: list[Message] = []  # 公开可读：transcript 即全部状态
        if system_prompt is not None:
            self.messages.append(Message(role="system", content=system_prompt))
        self.max_iterations = max_iterations
        self._hooks: dict[type[Event], list[Callable[[Event], HookResult | None]]] = {}

    def register_hook(self, event_cls, callback) -> None:
        """挂一个 hook 到事件类。同一事件可挂多个，按注册顺序触发，非 None 短路。"""
        self._hooks.setdefault(event_cls, []).append(callback)

    def unregister_hook(self, event_cls, callback) -> None:
        """移除 hook。"""
        self._hooks.get(event_cls, []).remove(callback)

    def _emit(self, event: Event) -> HookResult | None:
        """触发事件的所有 hook，返回第一个非 None 结果（短路）。纯观察事件无条件返回 None。"""
        for cb in self._hooks.get(type(event), []):
            result = cb(event)
            if result is not None:
                return result
        return None

    def run(self, user_input: str) -> str | None:
        """追加 user 消息 → 内联循环 → 返回最终文本（max_iterations 耗尽时 None）。"""
        user_msg = Message(role="user", content=user_input)
        self.messages.append(user_msg)
        self._emit(AgentStart())
        self._emit(MessageStart(user_msg))
        self._emit(MessageEnd(user_msg))
        iteration = 0
        while self.max_iterations is None or iteration < self.max_iterations:
            iteration += 1
            self._emit(TurnStart(iteration))
            # ── Reason：把完整消息历史 + 工具说明书发给模型。
            resp = self.llm.chat(messages=self.messages, tools=self.registry.get_schemas())
            assistant = Message(
                role="assistant",
                content=resp.content or "",
                metadata={"tool_calls": resp.tool_calls} if resp.tool_calls else None,
            )
            self.messages.append(assistant)
            self._emit(MessageStart(assistant))
            self._emit(MessageEnd(assistant))
            # ── 经典退出条件：模型不再发起工具调用 → 结束。
            if not resp.tool_calls:
                self._emit(AgentEnd(
                    messages=list(self.messages), final_text=resp.content,
                    iterations=iteration, stop_reason="end_turn"))
                return resp.content
            # ── Act + Observe：逐个执行本轮全部 tool_calls，结果写回 messages。
            tool_results: list[Message] = []
            for tc in resp.tool_calls:
                name, args, err, _hook = self._prepare_tool(tc)  # 内部触发 ToolExecutionStart + hook
                if err is not None:
                    observation, is_error = err, True
                else:
                    observation, is_error = self._execute_tool(tc, args)  # 内部触发 ToolExecutionEnd + hook
                tool_msg = Message(
                    role="tool", content=observation, metadata={"tool_call_id": tc["id"]})
                self.messages.append(tool_msg)
                self._emit(MessageStart(tool_msg))
                self._emit(MessageEnd(tool_msg))
                tool_results.append(tool_msg)
            self._emit(TurnEnd(message=assistant, tool_results=tool_results))
        self._emit(AgentEnd(
            messages=list(self.messages), final_text=None,
            iterations=iteration, stop_reason="max_iterations"))
        return None

    def reset(self) -> None:
        """清空 messages（保留 system prompt）。"""
        system = [m for m in self.messages if m.role == "system"]
        self.messages = system if system else []

    def _prepare_tool(self, tc: dict) -> tuple[str, dict, str | None, HookResult | None]:
        """解析 JSON + ToolExecutionStart hook 阶段：返回 (name, args, 错误文本或 None, hook)。永不抛。

        args 为实际生效参数（hook 改写后；畸形 JSON 时为空 dict）。
        err 非 None 表示该调用在 execute 前被拦截（畸形 JSON / hook block）。
        """
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, TypeError) as exc:
            return name, {}, f"Invalid JSON arguments for tool '{name}': {exc}", None
        # ToolExecutionStart hook：拦截（block）或改写（updated_args）
        try:
            hook = self._emit(ToolExecutionStart(tc["id"], name, args))
        except Exception as exc:  # hook 抛异常 → 转错误字符串，不中断循环
            return name, args, f"Error in ToolExecutionStart hook for '{name}': {exc}", None
        if hook is not None and hook.block:
            return name, args, f"Tool '{name}' blocked: {hook.reason}", hook
        if hook is not None and hook.updated_args is not None:
            args = hook.updated_args
        return name, args, None, hook

    def _execute_tool(self, tc: dict, args: dict) -> tuple[str, bool]:
        """执行阶段：以改写后 args 构造 effective 协议 dict → registry.execute → ToolExecutionEnd hook。永不抛。

        返回 (观察文本, is_error)。调用方保证 args 已通过 _prepare_tool 校验/改写。
        """
        name = tc["function"]["name"]
        # 执行：以改写后 args 生效（序列化回协议 dict 交给 registry）
        try:
            effective = {**tc, "function": {**tc["function"], "arguments": json.dumps(args)}}
            result = self.registry.execute(effective)
        except Exception as exc:  # json.dumps 兜底（registry.execute 自身声明永不抛）
            return f"Error executing tool '{name}': {exc}", True
        # ToolExecutionEnd hook：改写结果（updated_result）
        try:
            hook = self._emit(ToolExecutionEnd(tc["id"], name, result.serialize(), not result.ok))
        except Exception as exc:  # hook 抛异常 → 转错误字符串，不中断循环
            return f"Error in ToolExecutionEnd hook for '{name}': {exc}", True
        if hook is not None and hook.updated_result is not None:
            return hook.updated_result, False
        return result.serialize(), not result.ok
