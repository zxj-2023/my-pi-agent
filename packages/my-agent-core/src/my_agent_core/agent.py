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
    AssistantMessageAdded,
    Event,
    ToolCallEnd,
    ToolCallStart,
    TurnStart,
)
from my_agent_core.registry import ToolRegistry
from my_agent_core.tools import Tool, ToolResult


class ToolBlocked(Exception):
    """before_tool 拦截工具调用时抛出；reason 会变成错误结果喂回模型。"""


class Agent:
    """单层 Agent：持有 llm / 工具注册表 / 消息，内联 ReAct 循环。"""

    def __init__(
        self,
        *,
        llm: LLM,
        tools: list[Tool],
        system_prompt: str | None = None,
        max_iterations: int | None = None,
        on_event: Callable[[Event], None] | None = None,
        before_tool: Callable[[str, dict], dict] | None = None,
        after_tool: Callable[[str, dict, ToolResult], ToolResult] | None = None,
    ):
        """各参数语义见框架设计文档 §4.3。"""
        self.llm = llm
        self.registry = ToolRegistry()
        for t in tools:
            self.registry.register(t)
        self.messages: list[Message] = []  # 公开可读：transcript 即全部状态
        if system_prompt is not None:
            self.messages.append(Message(role="system", content=system_prompt))
        self.max_iterations = max_iterations
        self.on_event = on_event
        self.before_tool = before_tool
        self.after_tool = after_tool

    def run(self, user_input: str) -> str | None:
        """追加 user 消息 → 内联循环 → 返回最终文本（max_iterations 耗尽时 None）。"""

        def emit(event: Event) -> None:
            if self.on_event is not None:
                self.on_event(event)

        self.messages.append(Message(role="user", content=user_input))
        emit(AgentStart())
        iteration = 0
        while self.max_iterations is None or iteration < self.max_iterations:
            iteration += 1
            emit(TurnStart(iteration))
            # ── Reason：把完整消息历史 + 工具说明书发给模型。
            resp = self.llm.chat(messages=self.messages, tools=self.registry.get_schemas())
            assistant = Message(
                role="assistant",
                content=resp.content or "",
                metadata={"tool_calls": resp.tool_calls} if resp.tool_calls else None,
            )
            self.messages.append(assistant)
            emit(AssistantMessageAdded(assistant))
            # ── 经典退出条件：模型不再发起工具调用 → 结束。
            if not resp.tool_calls:
                emit(AgentEnd(resp.content, iteration, "end_turn"))
                return resp.content
            # ── Act + Observe：逐个执行本轮全部 tool_calls，结果写回 messages。
            for tc in resp.tool_calls:
                observation, is_error, args = self._execute_tool(tc)  # 永不抛；args 为实际生效参数
                emit(ToolCallStart(tc["id"], tc["function"]["name"], args))
                emit(ToolCallEnd(tc["id"], tc["function"]["name"], observation, is_error))
                self.messages.append(
                    Message(role="tool", content=observation, metadata={"tool_call_id": tc["id"]})
                )
        emit(AgentEnd(None, iteration, "max_iterations"))
        return None

    def reset(self) -> None:
        """清空 messages（保留 system prompt）。"""
        system = [m for m in self.messages if m.role == "system"]
        self.messages = system if system else []

    def _execute_tool(self, tc: dict) -> tuple[str, bool, dict]:
        """执行单个 tool_call：before_tool 拦截/改写 → registry.execute → after_tool 改写。永不抛。

        返回 (观察文本, is_error, args)。任何错误都走同一条路：错误字符串 + is_error=True。
        args 是实际生效的参数字典（含 before_tool 改写；畸形 JSON 时为空 dict）。
        """
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, TypeError) as exc:
            return f"Invalid JSON arguments for tool '{name}': {exc}", True, {}
        # before_tool：拦截（抛 ToolBlocked）或改写（返回新 args）
        if self.before_tool is not None:
            try:
                args = self.before_tool(name, args)
            except ToolBlocked as exc:
                return f"Tool '{name}' blocked: {exc}", True, args
            except Exception as exc:
                return f"Error in before_tool for '{name}': {exc}", True, args
        # 执行：以 before_tool 改写后的 args 生效（序列化回协议 dict 交给 registry）
        try:
            effective = {**tc, "function": {**tc["function"], "arguments": json.dumps(args)}}
            result = self.registry.execute(effective)
        except Exception as exc:  # json.dumps 兜底（registry.execute 自身声明永不抛）
            return f"Error executing tool '{name}': {exc}", True, args
        # after_tool：改写结果
        if self.after_tool is not None:
            try:
                result = self.after_tool(name, args, result)
            except Exception as exc:
                return f"Error in after_tool for '{name}': {exc}", True, args
        return result.serialize(), not result.ok, args
