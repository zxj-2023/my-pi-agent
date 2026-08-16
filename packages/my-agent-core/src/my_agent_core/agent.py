"""单层 Agent —— 状态 + 循环 + 工具执行全在一个类（pig-mono 式）。

模型调用 → 检查 tool_calls → 执行工具 → 观察结果写回消息 → 循环，
直到模型不再发起工具调用（经典退出条件：tool_calls 为空 → 结束）。

模型边界交给 my-agent-llm 的 LLM 门面；消息状态是 Message 对象列表。
"""
from __future__ import annotations

import json
from typing import Callable

from my_agent_llm import LLM, Message

from my_agent_core.context import ContextManager, ContextSessionBridge
from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    ContextCompacted,
    Event,
    HookResult,
    MessageEnd,
    MessageStart,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
)
from my_agent_core.registry import ToolRegistry
from my_agent_core.session import Session, build_initial_messages
from my_agent_core.tools import Tool

from pathlib import Path

from my_agent_core.skills import Skill, SkillManager
from my_agent_core.subagents import SubagentManager
from my_agent_core.tools.builtin import make_task_tool


class Agent:
    """单层 Agent：持有 llm / 工具注册表 / 消息，内联 ReAct 循环。"""

    # ── 构造与装配 ──────────────────────────────────────────

    def __init__(self, *, llm: LLM, tools: list[Tool], system_prompt: str | None = None,
                 max_iterations: int | None = None, session: Session | None = None,
                 context_budget: int | None = None, keep_recent_tokens: int | None = None,
                 skill_dirs: list[str | Path] | None = None,
                 model: str | None = None,
                 subagent_dirs: list[str | Path] | None = None):
        """各参数语义见框架设计文档 §4.3（hook 通过 register_hook 挂载）。

        session 非 None 为持久化模式：run() 内每条消息落盘；构造时从 session
        当前路径恢复 messages，此时 system_prompt 被忽略（文件为准，决策 5）。
        context_budget 为 context 预算：None → 用 ContextManager 默认（100k）；显式传 → 覆盖。
        context 默认启用（每次 llm.chat 前 prepare 压缩视图）。
        skill_dirs 为 skill 机制来源：None → 探测 <cwd>/.agents/skills（不存在则空）；
        [] → 显式禁用；非空 list → 只扫这些目录。构造 skill_manager 追加清单块进
        system；self.skill_manager 公开可读，self.skills = manager.list()（兼容代理）。
        正文由宿主 invoke_skill 显式注入（模型侧无 read 工具）。
        subagent_dirs 三态同 skill_dirs：None → 探测 <cwd>/.agents/agents；[] → 禁用；
        非空 → 只扫这些目录。有 agent 时清单追加进 system，且自动装配 task 工具。
        """
        self.llm = llm
        self.model = model          # 缺省 inherit：None 时 llm.chat 用 LLM 自身配置
        self.max_iterations = max_iterations
        self.session = session
        self._hooks: dict[type[Event], list[Callable[[Event], HookResult | None]]] = {}
        self.registry = ToolRegistry()
        self.skill_manager = SkillManager(skill_dirs)   # None→探测默认 / []→禁用 / 显式→目录
        self.skills: list[Skill] = self.skill_manager.list()   # 兼容代理
        self.subagent_manager = SubagentManager(subagent_dirs)   # 三态同 skill_dirs

        self._register_tools(tools)   # ① 工具注册统一（用户 + 内置 task）
        self.messages = build_initial_messages(   # ② 取初始 messages（session 恢复 or 拼 system）
            session, system_prompt=system_prompt,
            skill_manager=self.skill_manager, subagent_manager=self.subagent_manager,
        )
        self._init_context(session, context_budget, keep_recent_tokens)   # ③ context 装配

    def _register_tools(self, tools: list[Tool]) -> None:
        """注册用户工具 + 内置 task 工具（撞名 ValueError）。"""
        for t in tools:
            self.registry.register(t)
        if self.subagent_manager:
            if self.registry.get("task") is not None:
                raise ValueError("Tool name 'task' conflicts with the built-in subagent delegation tool")
            self.registry.register(make_task_tool(self.subagent_manager, self))

    def _init_context(self, session: Session | None, context_budget: int | None,
                      keep_recent_tokens: int | None) -> None:
        """装配 context 管理（默认启用）：context_budget None → 用 ContextManager 默认 budget。"""
        self._ctx_bridge = ContextSessionBridge(session) if session is not None else None
        self._ctx = ContextManager(
            llm=self.llm,
            keep_recent_tokens=keep_recent_tokens,
            results_dir=self._ctx_bridge.results_dir() if self._ctx_bridge else None,
            **({} if context_budget is None else {"budget": context_budget}),
        )
        if self._ctx_bridge is not None:
            self._ctx_bridge.restore_cache(self._ctx)

    # ── 公共 API ────────────────────────────────────────────

    def run(self, user_input: str) -> str | None:
        """追加 user 消息 → 内联循环 → 返回最终文本（max_iterations 耗尽时 None）。"""
        if self.session is not None:
            # 同步到 session 当前指针：rewind 后同 Agent 续跑时，内存 transcript 以文件为准
            self.messages = self.session.get_current_path_messages()
        user_msg = Message(role="user", content=user_input)
        self.messages.append(user_msg)
        if self.session is not None:
            self.session.add_message("user", user_input)
        self._emit(AgentStart())
        self._emit(MessageStart(user_msg))
        self._emit(MessageEnd(user_msg))
        iteration = 0
        while self.max_iterations is None or iteration < self.max_iterations:
            iteration += 1
            self._emit(TurnStart(iteration))
            # ── Reason：把完整消息历史 + 工具说明书发给模型。
            tools = self.registry.get_schemas()
            if self._ctx is not None:
                view = self._ctx.prepare(self.messages)
                resp = self._llm_chat(view, tools)
                if resp.usage:
                    self._ctx.record_usage(resp.usage)
                self._handle_compaction()
            else:
                resp = self._llm_chat(self.messages, tools)
            assistant = Message(
                role="assistant",
                content=resp.content or "",
                metadata={"tool_calls": resp.tool_calls} if resp.tool_calls else None,
            )
            self.messages.append(assistant)
            if self.session is not None:
                if resp.tool_calls:
                    self.session.add_message("assistant", assistant.content, tool_calls=resp.tool_calls)
                else:
                    self.session.add_message("assistant", assistant.content)
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
                # err 非 None 时它本身就是观察文本；否则执行工具（内部触发 ToolExecutionEnd + hook）
                observation = err if err is not None else self._execute_tool(tc, args)[0]
                tool_msg = Message(
                    role="tool", content=observation, metadata={"tool_call_id": tc["id"]})
                self.messages.append(tool_msg)
                if self.session is not None:
                    self.session.add_message("tool", observation, tool_call_id=tc["id"])
                self._emit(MessageStart(tool_msg))
                self._emit(MessageEnd(tool_msg))
                tool_results.append(tool_msg)
            self._emit(TurnEnd(message=assistant, tool_results=tool_results))
        self._emit(AgentEnd(
            messages=list(self.messages), final_text=None,
            iterations=iteration, stop_reason="max_iterations"))
        return None

    def invoke_skill(self, name: str, instructions: str = "") -> str | None:
        """显式调用：skill_manager.format_invocation 包装（未知名 ValueError）→
        self.run(包装文本) 跑一轮。"""
        return self.run(self.skill_manager.format_invocation(name, instructions))

    def reset(self) -> None:
        """清空 messages（保留 system prompt）。有 session 时同步清空树 + 重写文件。"""
        if self.session is not None:
            self.session.reset()
            self.messages = self.session.get_full_history_messages()
        else:
            system = [m for m in self.messages if m.role == "system"]
            self.messages = system if system else []
        if self._ctx is not None:
            self._ctx.reset()

    def compact(self) -> None:
        """手动触发压缩：无条件执行一次 L4 摘要（写缓存 + 事件），不动 messages。"""
        if self._ctx is None:
            return
        self._ctx.force_compact(self.messages)
        self._handle_compaction()

    def register_hook(self, event_cls, callback) -> None:
        """挂一个 hook 到事件类。同一事件可挂多个，按注册顺序触发，非 None 短路。"""
        self._hooks.setdefault(event_cls, []).append(callback)

    def unregister_hook(self, event_cls, callback) -> None:
        """移除 hook。"""
        self._hooks.get(event_cls, []).remove(callback)

    # ── 内部实现（run 循环辅助）──────────────────────────────

    def _llm_chat(self, messages, tools):
        """封装 llm.chat：透传 model（SDK 通用参数）。"""
        return self.llm.chat(messages=messages, tools=tools, model=self.model)

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
        # 防御：hook 违反契约返回非 HookResult 真值（如 True）时按无干预处理，避免 AttributeError 穿出
        if isinstance(hook, HookResult) and hook.block:
            return name, args, f"Tool '{name}' blocked: {hook.reason}", hook
        if isinstance(hook, HookResult) and hook.updated_args is not None:
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
        # 防御：hook 违反契约返回非 HookResult 真值（如 True）时按无干预处理，避免 AttributeError 穿出
        if isinstance(hook, HookResult) and hook.updated_result is not None:
            return hook.updated_result, False
        return result.serialize(), not result.ok

    def _handle_compaction(self) -> None:
        """prepare/force_compact 触发压缩后：写回 session（桥）+ 事件。"""
        if self._ctx is None:
            return
        if self._ctx_bridge is not None:
            self._ctx_bridge.write_compaction(self._ctx)
        info = self._ctx.pending_compaction
        if info is not None:
            self._emit(ContextCompacted(
                tokens_before=info.tokens_before,
                tokens_after=info.tokens_after,
                summarized_count=info.summarized_count,
            ))

    def _emit(self, event: Event) -> HookResult | None:
        """触发事件的所有 hook，返回第一个非 None 结果（短路）。纯观察事件无条件返回 None。"""
        for cb in self._hooks.get(type(event), []):
            result = cb(event)
            if result is not None:
                return result
        return None
