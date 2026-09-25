# pyright: reportImportCycles=false
"""单层 Agent —— 状态 + 循环 + 工具执行全在一个类（原生异步驱动）。

模型调用 → 检查 tool_calls → 执行工具 → 观察结果写回消息 → 循环，
直到模型不再发起工具调用（经典退出条件：tool_calls 为空 → 结束）。

模型边界交给 my-agent-llm 的 LLM 门面；消息状态是 Message 对象列表。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from my_agent_core.background import (  # pyright: ignore[reportMissingImports]
    BackgroundRunner,
)
from my_agent_core.context import ContextManager, ContextSessionBridge
from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    ContextCompacted,
    Event,
    MessageEnd,
    TurnEnd,
)
from my_agent_core.extensions import ExtensionManager
from my_agent_core.hooks import (  # pyright: ignore[reportMissingImports]
    AgentStartHook,
    HookRegistry,
    HookResult,
    UserInputHook,
)
from my_agent_core.loop import CancellationToken, run_agent_loop
from my_agent_core.memory import MemoryStore, make_memory_tool
from my_agent_core.message_queue import MessageQueue, QueuedMessage
from my_agent_core.plugins import PluginManager
from my_agent_core.registry import ToolRegistry
from my_agent_core.retry import AutoRetryPolicy  # pyright: ignore[reportMissingImports]
from my_agent_core.session import Session
from my_agent_core.skills import Skill, SkillManager
from my_agent_core.subagents import SubagentManager
from my_agent_core.task_store import TaskStore  # pyright: ignore[reportMissingImports]
from my_agent_core.tool_history import repair_tool_history
from my_agent_core.tools import Tool
from my_agent_core.tools.builtin.task import (
    make_task_tool,  # pyright: ignore[reportMissingImports]
)
from my_agent_core.tools.builtin.task_tools import (  # pyright: ignore[reportMissingImports]
    TaskGuardHook,
    make_task_tools,
)
from my_agent_llm import LLM, Message  # pyright: ignore[reportMissingImports]


class Agent:
    """单层 Agent：持有 llm / 工具注册表 / 消息，内联 ReAct 异步循环。"""

    # ── 构造与装配 ──────────────────────────────────────────

    def __init__(
        self,
        *,
        llm: LLM,
        tools: list[Tool],
        session: Session,
        system_prompt: str | None = None,
        max_iterations: int | None = None,
        context_budget: int | None = None,
        keep_recent_tokens: int | None = None,
        skill_dirs: Sequence[str | Path] | None = None,
        model: str | None = None,
        subagent_dirs: Sequence[str | Path] | None = None,
        extension_dirs: Sequence[str | Path] | None = None,
        plugin_dirs: Sequence[str | Path] | None = None,
        memory_dir: str | Path | None | Literal[False] = None,
        task_store: TaskStore | Path | str | None | Literal[False] = None,
        steering_mode: Literal["one-at-a-time", "all"] = "one-at-a-time",
        followup_mode: Literal["one-at-a-time", "all"] = "one-at-a-time",
        hooks: list[tuple[type, Callable[..., Any]]] | None = None,
        retry_policy: AutoRetryPolicy | None = None,
    ):
        """各参数语义见框架设计文档 §4.3（hook 通过 register_hook 挂载）。

        session 必填：run() 内每条消息落盘；构造时从 session 当前路径恢复纯对话，
        并用 system_prompt + skill 清单 + subagent 清单拼 system（消息首条）。
        context_budget 为 context 预算：None → 用 ContextManager 默认（100k）；显式传 → 覆盖。
        context 默认启用（每次 llm.chat 前 prepare 压缩视图）。
        skill_dirs 为 skill 机制来源：None → 探测 <cwd>/.agents/skills（不存在则空）；
        [] → 显式禁用；非空 list → 只扫这些目录。构造 skill_manager 追加清单块进
        system；self.skill_manager 公开可读，self.skills 为动态计算属性（@property 代理 manager.list()）。
        正文由宿主 invoke_skill 显式注入（模型侧无 read 工具）。
        subagent_dirs 三态同 skill_dirs：None → 探测 <cwd>/.agents/agents；[] → 禁用；
        非空 → 只扫这些目录。有 agent 时清单追加进 system，且自动装配 task 工具。
        extension_dirs 三态同 skill_dirs/subagent_dirs：None → 探测 <cwd>/.agents/extensions；
        [] → 禁用；非空 → 只扫这些目录。extension 在 _register_tools 之后加载，注册的工具可覆盖
        内置工具（对齐 pi）；hook 注册进 hooks（先于构造参数 hooks 触发）；命令存 extension_manager，
        上层 CLI 调 handle_command 派发。
        plugin_dirs 为 Claude Code 格式插件目录：None → 探测 <cwd>/.agents/plugins；
        [] → 显式禁用；非空 list → 扫各插件目录并自动解构其 skills/、agents/ 注入对应管理器。
        memory_dir 为持久化记忆存储目录：None → 探测 <cwd>/.my_agent_core/memory（存在才启用）；
        False → 显式禁用；str | Path → 显式指定目录。启用时构造 MemoryStore 并冻结快照，
        自动注入 <MEMORY_CONTEXT> 块进 system，并自动注册 memory 工具（add/replace/remove）。
        """
        self.llm = llm
        self.model = model  # 缺省 inherit：None 时 llm.chat 用 LLM 自身配置
        self.max_iterations = max_iterations
        self.session = session
        self._system_prompt = system_prompt  # 保存，reset 重拼用
        self._aborted = False  # 中止状态标记
        self._current_signal: CancellationToken | None = None
        self._subscribers: list[Callable[[Event], Any]] = []
        self.hooks = HookRegistry()
        self.registry = ToolRegistry()
        self.plugin_manager = PluginManager(plugin_dirs)
        self.skill_manager = SkillManager(
            skill_dirs, extra_dirs=self.plugin_manager.get_skill_dirs()
        )  # None→探测默认 / []→禁用 / 显式→目录
        self.subagent_manager = SubagentManager(
            subagent_dirs, extra_dirs=self.plugin_manager.get_subagent_dirs()
        )  # 三态同 skill_dirs

        self.memory_store = self._init_memory_store(memory_dir)  # memory 装配与快照冻结
        self.task_store = self._init_task_store(task_store)  # 任务看板仓库装配
        self.retry_policy = retry_policy or AutoRetryPolicy()  # 大模型自动重试策略
        self.message_queue = MessageQueue(
            steering_mode=steering_mode, followup_mode=followup_mode
        )  # 动态干预消息队列 (Pi-style steer & followup)
        self.background_runner = BackgroundRunner(self.message_queue)  # 后台异步执行器与孤儿进程防御调度引擎

        self._register_tools(tools)  # ① 工具注册统一（用户 + 内置 task + 内置 memory）
        self.extension_manager = ExtensionManager(self, extension_dirs)  # extension 装配
        self._extensions_loaded = False
        self.messages = self._init_messages(session, system_prompt)  # ② 拼 system + 恢复
        self._init_context(session, context_budget, keep_recent_tokens)  # ③ context 装配
        self._register_hooks(hooks)  # ④ hooks 批量注册

    def _init_task_store(self, task_store: TaskStore | Path | str | None | Literal[False]) -> TaskStore | None:
        """解析 task_store 三态并初始化 TaskStore：
        False → 显式禁用；
        TaskStore 实例 → 直接复用；
        str | Path → 指定工作区初始化；
        None → 探测 <cwd>/.my_agent_core/tasks.json（存在才启用）。
        """
        if isinstance(task_store, bool) and not task_store:
            return None
        if isinstance(task_store, TaskStore):
            return task_store
        if task_store is not None:
            return TaskStore(task_store)
        default_file = Path.cwd() / ".my_agent_core" / "tasks.json"
        if default_file.exists() and default_file.is_file():
            return TaskStore(Path.cwd())
        return None

    def _init_memory_store(self, memory_dir: str | Path | None | Literal[False]) -> MemoryStore | None:
        """解析 memory_dir 三态并初始化 MemoryStore：
        False → 显式禁用；
        None → 探测 <cwd>/.my_agent_core/memory（存在才启用）；
        str | Path → 显式指定目录。
        """
        if isinstance(memory_dir, bool) and not memory_dir:
            return None
        if memory_dir is not None:
            store = MemoryStore(memory_dir)
            store.load_from_disk()
            return store
        default_dir = Path.cwd() / ".my_agent_core" / "memory"
        if default_dir.exists() and default_dir.is_dir():
            store = MemoryStore(default_dir)
            store.load_from_disk()
            return store
        return None

    def _register_tools(self, tools: list[Tool]) -> None:
        """注册用户工具 + 内置 task 工具 + 内置 memory 工具（撞名 ValueError）。"""
        for t in tools:
            self.registry.register(t)
        if self.subagent_manager:
            if self.registry.get("task") is not None:
                raise ValueError("Tool name 'task' conflicts with the built-in subagent delegation tool")
            self.registry.register(make_task_tool(self.subagent_manager, self))
        if self.memory_store:
            if self.registry.get("memory") is not None:
                raise ValueError("Tool name 'memory' conflicts with the built-in memory tool")
            self.registry.register(make_memory_tool(self.memory_store))
        if self.task_store:
            for task_tool in make_task_tools(self.task_store):
                if self.registry.get(task_tool.name) is not None:
                    raise ValueError(f"Tool name '{task_tool.name}' conflicts with built-in task tool")
                self.registry.register(task_tool)

    def _init_messages(self, session: Session, system_prompt: str | None) -> list[Message]:
        """拼 system（Agent 配置）+ 恢复 session 纯对话，合成初始 messages。"""
        mem_prompt = self.memory_store.format_all_for_system_prompt() if self.memory_store else None
        parts = [
            p
            for p in (
                system_prompt or "",
                self.skill_manager.format_prompt(),
                self.subagent_manager.format_prompt(),
                mem_prompt,
            )
            if p
        ]
        messages = session.get_full_history_messages()  # 纯对话（不含 system）
        if parts:
            messages.insert(0, Message(role="system", content="\n\n".join(parts)))
        return messages

    def _init_context(
        self,
        session: Session,
        context_budget: int | None,
        keep_recent_tokens: int | None,
    ) -> None:
        """装配 context 管理（默认启用）：context_budget None → 用 ContextManager 默认 budget。"""
        self._ctx_bridge = ContextSessionBridge(session)
        self._ctx = ContextManager(
            llm=self.llm,
            keep_recent_tokens=keep_recent_tokens,
            results_dir=self._ctx_bridge.results_dir(),
            **({} if context_budget is None else {"budget": context_budget}),
        )
        self._ctx_bridge.restore_cache(self._ctx)

    def _register_hooks(self, hooks: list[tuple[type, Callable[..., Any]]] | None) -> None:
        """构造时批量注册 hooks / 决策回调（对称 _register_tools）。"""
        if self.task_store:
            guard = TaskGuardHook(self.task_store, self.steer)
            self.subscribe(lambda ev: guard.on_agent_start(ev) if isinstance(ev, AgentStart) else None)
            self.subscribe(lambda ev: guard.on_turn_end(ev) if isinstance(ev, TurnEnd) else None)
        for target, callback in hooks or []:
            self.hooks.register(target, callback)

    # ── 公共 API ────────────────────────────────────────────

    @property
    def context_manager(self) -> ContextManager:
        """底层上下文管理器。"""
        return self._ctx

    @property
    def skills(self) -> list[Skill]:
        """动态获取当前注册的全部技能列表。"""
        return self.skill_manager.list()

    @property
    def system_prompt(self) -> str | None:
        """Agent 配置的初始系统提示词。"""
        return self._system_prompt

    def abort(self) -> None:
        """中止当前运行中的任务（取消流式输出，丢弃未完成半截文本并清空干预队列）。"""
        self._aborted = True
        if self._current_signal is not None:
            self._current_signal.cancel()
        self.message_queue.clear()
        asyncio.create_task(self.background_runner.cancel_all())

    def subscribe(self, listener: Callable[[Event], Any]) -> Callable[[], None]:
        """订阅所有生命周期事件通知，返回取消订阅的回调函数。"""
        self._subscribers.append(listener)

        def unsubscribe() -> None:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

        return unsubscribe

    def steer(self, message: str) -> None:
        """注入即时转向指令（在下一个安全点打断/干预模型执行路线）。"""
        self.message_queue.add_steering(message)

    def follow_up(self, message: str) -> None:
        """追加排队追问指令（在当前任务彻底完成后自动开启下一段任务）。"""
        self.message_queue.add_followup(message)

    def clear_queue(self) -> list[QueuedMessage]:
        """清空当前排队的干预消息（包含 Steering 与 Follow-up），并返回被清除的消息列表。"""
        return self.message_queue.clear()

    def _get_steering_messages(self) -> Sequence[str]:
        """为底层循环提取当前排队的 steer 消息。"""
        if self.message_queue.has_steering():
            return [m.content for m in self.message_queue.get_steering_messages()]
        return []

    def _get_follow_up_messages(self) -> Sequence[str]:
        """为底层循环提取当前排队的 follow-up 消息。"""
        if self.message_queue.has_followup():
            return [m.content for m in self.message_queue.get_followup_messages()]
        return []

    async def prompt_stream(self, user_input: str) -> AsyncIterator[Event]:
        """原生事件流一等公民接口：调用 run_agent_loop 执行 ReAct 循环，逐一产生生命周期事件，并更新 session 与 messages。"""
        self._aborted = False
        self._current_signal = CancellationToken()

        if not self._extensions_loaded:
            await self.extension_manager.load()
            self._extensions_loaded = True

        # ── Hook 1: UserInputHook 拦截与改写（在进入 Session 和消息历史之前触发）
        user_input_decision = await self.hooks.emit(UserInputHook(input_text=user_input))
        if isinstance(user_input_decision, HookResult):
            if user_input_decision.block:
                reason = f": {user_input_decision.reason}" if user_input_decision.reason else ""
                end_ev = AgentEnd(
                    messages=list(self.messages),
                    final_text=f"(blocked{reason})",
                    iterations=0,
                    stop_reason="blocked",
                )
                await self._notify(end_ev)
                yield end_ev
                return
            if user_input_decision.updated_input is not None:
                user_input = user_input_decision.updated_input

        # 同步到 session 当前指针：rewind 后同 Agent 续跑时，内存 transcript 以文件为准。
        system = [m for m in self.messages if m.role == "system"]
        restored = system + self.session.get_full_history_messages()
        # 对齐 Tau: 执行对话历史自愈，保证送入模型的会话转录本没有悬空断头 ToolCall
        self.messages = list(repair_tool_history(restored).messages)

        # 准备 system_prompt
        system_prompt = self.system_prompt or ""
        system_msgs = [m for m in self.messages if m.role == "system"]
        if system_msgs:
            system_prompt = system_msgs[0].content

        # ── Hook 2: AgentStartHook 拦截启动或动态重写 system_prompt
        start_decision = await self.hooks.emit(AgentStartHook(system_prompt=system_prompt))
        if isinstance(start_decision, HookResult):
            if start_decision.block:
                reason = f": {start_decision.reason}" if start_decision.reason else ""
                end_ev = AgentEnd(
                    messages=list(self.messages),
                    final_text=f"(blocked{reason})",
                    iterations=0,
                    stop_reason="blocked",
                )
                await self._notify(end_ev)
                yield end_ev
                return
            if start_decision.updated_system_prompt is not None:
                system_prompt = start_decision.updated_system_prompt
                if self.messages and self.messages[0].role == "system":
                    self.messages[0] = Message(role="system", content=system_prompt)
                elif system_prompt:
                    self.messages.insert(0, Message(role="system", content=system_prompt))

        # 委托核心 ReAct 纯函数微内核驱动事件流
        loop_gen = run_agent_loop(
            llm=self.llm,
            messages=self.messages,
            tools=self.registry,
            context_manager=self._ctx,
            model=self.model,
            system=system_prompt,
            prompts=[Message(role="user", content=user_input)],
            max_iterations=self.max_iterations,
            signal=self._current_signal,
            get_steering_messages=self._get_steering_messages,
            get_follow_up_messages=self._get_follow_up_messages,
            before_model_call=self.hooks.emit,
            before_tool_call=self.hooks.emit,
            after_tool_call=self.hooks.emit,
            retry_policy=self.retry_policy,
        )

        async for event in loop_gen:
            # 同步 Session 状态与压缩写回
            if isinstance(event, MessageEnd):
                msg = event.message
                is_cancelled_partial_text = (
                    msg.role == "assistant"
                    and not (msg.metadata and msg.metadata.get("tool_calls"))
                    and (bool(msg.metadata and msg.metadata.get("stop_reason") == "cancelled") or self._aborted)
                )
                if msg.role != "system" and not is_cancelled_partial_text:
                    self.session.add_message(msg.role, msg.content, **(msg.metadata or {}))
            elif isinstance(event, ContextCompacted):
                self._ctx_bridge.write_compaction(self._ctx)

            # 分发到订阅者
            await self._notify(event)

            yield event

    async def run(self, user_input: str) -> str | None:
        """追加 user 消息 → 内部消费 prompt_stream 事件流 → 返回最终文本。"""
        final_text = None
        async for event in self.prompt_stream(user_input):
            if isinstance(event, AgentEnd):
                if event.stop_reason == "cancelled":
                    return "(cancelled)"
                if event.stop_reason == "blocked":
                    return event.final_text or "(blocked)"
                if event.stop_reason == "error":
                    raise RuntimeError(event.final_text or "Error during model stream")
                final_text = event.final_text
        return final_text

    async def invoke_skill(self, name: str, instructions: str = "") -> str | None:
        """显式调用：skill_manager.format_invocation 包装（未知名 ValueError）→
        self.run(包装文本) 跑一轮。"""
        return await self.run(self.skill_manager.format_invocation(name, instructions))

    def reset(self) -> None:
        """清空对话（保留 system）。session 树清空 + 重载 memory 快照并重拼 system，清空干预队列。"""
        self.message_queue.clear()
        self.session.reset()
        if self.memory_store:
            self.memory_store.load_from_disk()
        self.messages = self._init_messages(self.session, self._system_prompt)
        self._ctx.reset()

    async def compact(self, instructions: str | None = None) -> None:
        """手动触发压缩：无条件执行一次 L4 摘要（写缓存 + 事件），不动 messages。"""
        await self._ctx.compact(self.messages, instructions=instructions)
        await self._handle_compaction()

    # ── 内部实现 ─────────────────────────────────────────────

    async def _notify(self, event: Event) -> None:
        """将生命周期事件安全广播给所有旁路订阅者（对标 Tau AgentHarness._notify）。"""
        for sub in list(self._subscribers):
            with contextlib.suppress(Exception):
                res = sub(event)
                if inspect.isawaitable(res):
                    await res

    async def _handle_compaction(self) -> None:
        """prepare/force_compact 触发压缩后：写回 session（桥）+ 事件。"""
        self._ctx_bridge.write_compaction(self._ctx)
        info = self._ctx.pending_compaction
        if info is not None:
            ev = ContextCompacted(
                tokens_before=info.tokens_before,
                tokens_after=info.tokens_after,
                summarized_count=info.summarized_count,
            )
            await self._notify(ev)
