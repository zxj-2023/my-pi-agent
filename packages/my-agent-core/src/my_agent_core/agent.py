"""单层 Agent —— 状态 + 循环 + 工具执行全在一个类（原生异步驱动）。

模型调用 → 检查 tool_calls → 执行工具 → 观察结果写回消息 → 循环，
直到模型不再发起工具调用（经典退出条件：tool_calls 为空 → 结束）。

模型边界交给 my-agent-llm 的 LLM 门面；消息状态是 Message 对象列表。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from my_agent_llm import LLM, Message  # pyright: ignore[reportMissingImports]

from my_agent_core.background import (  # pyright: ignore[reportMissingImports]
    BackgroundRunner,
)
from my_agent_core.context import ContextManager, ContextSessionBridge
from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    BeforeModelCall,
    ContextCompacted,
    Event,
    HookRegistry,
    HookResult,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
    UserInput,
)
from my_agent_core.extensions import ExtensionManager
from my_agent_core.memory import MemoryStore, make_memory_tool
from my_agent_core.message_queue import MessageQueue, QueuedMessage
from my_agent_core.plugins import PluginManager
from my_agent_core.registry import ToolRegistry
from my_agent_core.session import Session
from my_agent_core.skills import Skill, SkillManager
from my_agent_core.subagents import SubagentManager
from my_agent_core.task_store import TaskStore  # pyright: ignore[reportMissingImports]
from my_agent_core.tools import Tool, ToolResult
from my_agent_core.tools.builtin.task import make_task_tool  # pyright: ignore[reportMissingImports]
from my_agent_core.tools.builtin.task_tools import (  # pyright: ignore[reportMissingImports]
    make_task_tools,
)


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
        hooks: list[tuple[type[Event], Callable]] | None = None,
    ):
        """各参数语义见框架设计文档 §4.3（hook 通过 register_hook 挂载）。

        session 必填：run() 内每条消息落盘；构造时从 session 当前路径恢复纯对话，
        并用 system_prompt + skill 清单 + subagent 清单拼 system（消息首条）。
        context_budget 为 context 预算：None → 用 ContextManager 默认（100k）；显式传 → 覆盖。
        context 默认启用（每次 llm.chat 前 prepare 压缩视图）。
        skill_dirs 为 skill 机制来源：None → 探测 <cwd>/.agents/skills（不存在则空）；
        [] → 显式禁用；非空 list → 只扫这些目录。构造 skill_manager 追加清单块进
        system；self.skill_manager 公开可读，self.skills = manager.list()（兼容代理）。
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
        self.hooks = HookRegistry()
        self.registry = ToolRegistry()
        self.plugin_manager = PluginManager(plugin_dirs)
        self.skill_manager = SkillManager(
            skill_dirs, extra_dirs=self.plugin_manager.get_skill_dirs()
        )  # None→探测默认 / []→禁用 / 显式→目录
        self.skills: list[Skill] = self.skill_manager.list()  # 兼容代理
        self.subagent_manager = SubagentManager(
            subagent_dirs, extra_dirs=self.plugin_manager.get_subagent_dirs()
        )  # 三态同 skill_dirs

        self.memory_store = self._init_memory_store(memory_dir)  # memory 装配与快照冻结
        self.task_store = self._init_task_store(task_store)  # 任务看板仓库装配
        self.message_queue = MessageQueue(
            steering_mode=steering_mode, followup_mode=followup_mode
        )  # 动态干预消息队列 (Pi-style steer & followup)
        self.background_runner = BackgroundRunner(
            self.message_queue
        )  # 后台异步执行器与孤儿进程防御调度引擎

        self._register_tools(tools)  # ① 工具注册统一（用户 + 内置 task + 内置 memory）
        self.extension_manager = ExtensionManager(
            self, extension_dirs
        )  # extension 装配
        self._extensions_loaded = False
        self.messages = self._init_messages(
            session, system_prompt
        )  # ② 拼 system + 恢复
        self._init_context(
            session, context_budget, keep_recent_tokens
        )  # ③ context 装配
        self._register_hooks(hooks)  # ④ hooks 批量注册

    def _init_task_store(
        self, task_store: TaskStore | Path | str | None | Literal[False]
    ) -> TaskStore | None:
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

    def _init_memory_store(
        self, memory_dir: str | Path | None | Literal[False]
    ) -> MemoryStore | None:
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
                raise ValueError(
                    "Tool name 'task' conflicts with the built-in subagent delegation tool"
                )
            self.registry.register(make_task_tool(self.subagent_manager, self))
        if self.memory_store:
            if self.registry.get("memory") is not None:
                raise ValueError(
                    "Tool name 'memory' conflicts with the built-in memory tool"
                )
            self.registry.register(make_memory_tool(self.memory_store))
        if self.task_store:
            for task_tool in make_task_tools(self.task_store):
                if self.registry.get(task_tool.name) is not None:
                    raise ValueError(
                        f"Tool name '{task_tool.name}' conflicts with built-in task tool"
                    )
                self.registry.register(task_tool)

    def _init_messages(
        self, session: Session, system_prompt: str | None
    ) -> list[Message]:
        """拼 system（Agent 配置）+ 恢复 session 纯对话，合成初始 messages。"""
        mem_prompt = (
            self.memory_store.format_all_for_system_prompt()
            if self.memory_store
            else None
        )
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

    def _register_hooks(self, hooks) -> None:
        """构造时批量注册 hooks（对称 _register_tools）。"""
        for event_cls, callback in hooks or []:
            self.hooks.register(event_cls, callback)

    # ── 公共 API ────────────────────────────────────────────

    @property
    def system_prompt(self) -> str | None:
        """Agent 配置的初始系统提示词。"""
        return self._system_prompt

    def abort(self) -> None:
        """中止当前运行中的任务（取消流式输出，丢弃未完成半截文本并清空干预队列）。"""
        self._aborted = True
        self.message_queue.clear()
        asyncio.create_task(self.background_runner.cancel_all())

    def steer(self, message: str) -> None:
        """注入即时转向指令（在下一个安全点打断/干预模型执行路线）。"""
        self.message_queue.add_steering(message)

    def follow_up(self, message: str) -> None:
        """追加排队追问指令（在当前任务彻底完成后自动开启下一段任务）。"""
        self.message_queue.add_followup(message)

    def clear_queue(self) -> list[QueuedMessage]:
        """清空未消费的消息队列。"""
        return self.message_queue.clear()

    def get_queue_status(self) -> str:
        """返回当前消息队列排队状态。"""
        return self.message_queue.get_status()

    async def run(self, user_input: str) -> str | None:
        """追加 user 消息 → 异步内联双层循环 → 返回最终文本（max_iterations 耗尽时 None）。"""
        self._aborted = False
        if not self._extensions_loaded:
            await self.extension_manager.load()
            self._extensions_loaded = True

        # ── 决策点 1: UserInput 拦截与改写（在进入 Session 和消息历史之前触发）
        input_hook = await self._emit(UserInput(input_text=user_input))
        if isinstance(input_hook, HookResult):
            if input_hook.block:
                reason = f": {input_hook.reason}" if input_hook.reason else ""
                return f"(blocked{reason})"
            if input_hook.updated_input is not None:
                user_input = input_hook.updated_input

        # 同步到 session 当前指针：rewind 后同 Agent 续跑时，内存 transcript 以文件为准。
        system = [m for m in self.messages if m.role == "system"]
        self.messages = system + self.session.get_current_path_messages()

        # ── 决策点 2: AgentStart 拦截与动态 System Prompt 改写
        start_hook = await self._emit(
            AgentStart(system_prompt=self.system_prompt or "", user_input=user_input)
        )
        if isinstance(start_hook, HookResult):
            if start_hook.block:
                reason = f": {start_hook.reason}" if start_hook.reason else ""
                return f"(blocked{reason})"
            if start_hook.updated_system_prompt is not None:
                if self.messages and self.messages[0].role == "system":
                    self.messages[0] = Message(
                        role="system", content=start_hook.updated_system_prompt
                    )
                else:
                    self.messages.insert(
                        0,
                        Message(
                            role="system",
                            content=start_hook.updated_system_prompt,
                        ),
                    )

        user_msg = Message(role="user", content=user_input)
        self.messages.append(user_msg)
        self.session.add_message("user", user_input)
        await self._emit(MessageStart(user_msg))
        await self._emit(MessageEnd(user_msg))

        pending_messages: list[str] = []
        if self.message_queue.has_steering():
            pending_messages.extend(
                [m.content for m in self.message_queue.get_steering_messages()]
            )

        iteration = 0
        final_text: str | None = None

        # ══════════════════════════════════════════════════════════════
        # 【外层循环】：处理 Follow-up 宏观任务衔接
        # ══════════════════════════════════════════════════════════════
        while True:
            has_more_tool_calls = True

            # ──────────────────────────────────────────────────────────
            # 【内层循环】：处理单任务的 ReAct 迭代与 Steer 即时转向
            # ──────────────────────────────────────────────────────────
            while has_more_tool_calls or len(pending_messages) > 0:
                iteration += 1
                if self._aborted:
                    await self._emit(
                        AgentEnd(
                            messages=list(self.messages),
                            final_text=None,
                            iterations=iteration,
                            stop_reason="cancelled",
                        )
                    )
                    return "(cancelled)"

                if self.max_iterations is not None and iteration > self.max_iterations:
                    await self._emit(
                        AgentEnd(
                            messages=list(self.messages),
                            final_text=final_text,
                            iterations=iteration,
                            stop_reason="max_iterations",
                        )
                    )
                    return final_text

                await self._emit(TurnStart(iteration))

                # ① 安全点 1 (Turn 起始点注入 pending 消息并原子落盘)
                if pending_messages:
                    for text in pending_messages:
                        msg = Message(role="user", content=text)
                        self.messages.append(msg)
                        self.session.add_message("user", text)
                        await self._emit(MessageStart(msg))
                        await self._emit(MessageEnd(msg))
                    pending_messages = []

                # ── Reason：准备上下文视图 + 异步流式调大模型
                tools = self.registry.get_schemas()
                view = await self._ctx.prepare(self.messages)

                # ── 看板自动投影（若有任务，动态注入到模型临时视图中，Session 零污染）
                if self.task_store and self.task_store.list():
                    board_block = f"<TASK_BOARD>\n{self.task_store.render_board()}\n</TASK_BOARD>"
                    view = list(view)
                    if view and view[0].role == "system":
                        view[0] = Message(
                            role="system",
                            content=view[0].content + f"\n\n{board_block}",
                        )
                    else:
                        view.insert(0, Message(role="system", content=board_block))

                # ── 决策点 3: BeforeModelCall 临时视图改写（self.messages 与 Session 零污染）
                ctx_hook = await self._emit(
                    BeforeModelCall(messages=list(view), iteration=iteration)
                )
                if isinstance(ctx_hook, HookResult):
                    if ctx_hook.block:
                        reason = ctx_hook.reason or "blocked"
                        await self._emit(
                            AgentEnd(
                                messages=list(self.messages),
                                final_text=None,
                                iterations=iteration,
                                stop_reason="blocked",
                            )
                        )
                        return f"(blocked: {reason})"
                    if ctx_hook.updated_messages is not None:
                        view = ctx_hook.updated_messages

                content_acc = ""
                final_tool_calls = None
                last_usage = None
                cancelled = False

                if hasattr(self.llm, "achat_stream"):
                    stream = self.llm.achat_stream(
                        messages=view, tools=tools, model=self.model
                    )
                    async for chunk in stream:
                        if self._aborted:
                            cancelled = True
                            break

                        if chunk.content:
                            content_acc += chunk.content
                        if getattr(chunk, "tool_calls", None):
                            final_tool_calls = chunk.tool_calls
                        if getattr(chunk, "usage", None):
                            last_usage = chunk.usage

                        hook = await self._emit(
                            MessageUpdate(
                                message=Message(role="assistant", content=content_acc),
                                chunk=chunk,
                            )
                        )
                        if isinstance(hook, HookResult) and hook.block:
                            self._aborted = True
                            cancelled = True
                            break
                elif hasattr(self.llm, "achat"):
                    resp = await self.llm.achat(
                        messages=view, tools=tools, model=self.model
                    )
                    content_acc = resp.content or ""
                    final_tool_calls = resp.tool_calls
                    last_usage = resp.usage
                else:
                    resp = self._llm_chat(view, tools)
                    content_acc = resp.content or ""
                    final_tool_calls = resp.tool_calls
                    last_usage = resp.usage

                if cancelled or self._aborted:
                    await self._emit(
                        AgentEnd(
                            messages=list(self.messages),
                            final_text=None,
                            iterations=iteration,
                            stop_reason="cancelled",
                        )
                    )
                    return "(cancelled)"

                if last_usage:
                    self._ctx.record_usage(last_usage)
                await self._handle_compaction()

                assistant = Message(
                    role="assistant",
                    content=content_acc,
                    metadata={"tool_calls": final_tool_calls}
                    if final_tool_calls
                    else None,
                )
                self.messages.append(assistant)
                self.session.add_message(
                    "assistant", assistant.content, **(assistant.metadata or {})
                )
                await self._emit(MessageStart(assistant))
                await self._emit(MessageEnd(assistant))

                # ── 检查是否有工具调用
                if final_tool_calls:
                    tool_call_dicts = final_tool_calls
                    prepared_calls: list[
                        tuple[int, dict[str, Any], dict[str, Any]]
                    ] = []
                    direct_observations: dict[int, ToolResult] = {}

                    for idx, tc in enumerate(tool_call_dicts):
                        name, args, err, _hook = await self._prepare_tool(tc)
                        if err is not None:
                            direct_observations[idx] = ToolResult(ok=False, error=err)
                        else:
                            prepared_calls.append((idx, tc, args))

                    if prepared_calls:
                        effective_calls = [
                            (
                                idx,
                                {
                                    **tc,
                                    "function": {
                                        **tc["function"],
                                        "arguments": json.dumps(args),
                                    },
                                },
                            )
                            for idx, tc, args in prepared_calls
                        ]
                        call_dicts_to_run = [c[1] for c in effective_calls]
                        batch_results = await self.registry.execute_batch(
                            call_dicts_to_run
                        )
                        for (idx, _tc), res in zip(
                            effective_calls, batch_results, strict=False
                        ):
                            obs, is_err = await self._post_execute_hook(_tc, res)
                            direct_observations[idx] = (
                                ToolResult(ok=not is_err, data=obs)
                                if not is_err
                                else ToolResult(ok=False, error=obs)
                            )

                    # 保序写回 messages 和 session
                    tool_results: list[Message] = []
                    for idx, tc in enumerate(tool_call_dicts):
                        res = direct_observations[idx]
                        observation = res.serialize()
                        tool_msg = Message(
                            role="tool",
                            content=observation,
                            metadata={"tool_call_id": tc["id"]},
                        )
                        self.messages.append(tool_msg)
                        self.session.add_message(
                            "tool", observation, tool_call_id=tc["id"]
                        )
                        await self._emit(MessageStart(tool_msg))
                        await self._emit(MessageEnd(tool_msg))
                        tool_results.append(tool_msg)

                    has_more_tool_calls = True
                else:
                    tool_results = []
                    has_more_tool_calls = False
                    final_text = content_acc

                # 每个 Turn 结束时统一派发 TurnEnd（对齐 Pi 标准生命周期：每轮必有配对的 TurnEnd）
                await self._emit(TurnEnd(message=assistant, tool_results=tool_results))

                # ② & ③ 安全点：在 Turn 结束时检查 Steer 转向
                if self.message_queue.has_steering():
                    steer_msgs = self.message_queue.get_steering_messages()
                    pending_messages = [m.content for m in steer_msgs]

            # ──────────────────────────────────────────────────────────
            # 内层循环自然结束 (无 tool_calls 且无 steering)
            # ──────────────────────────────────────────────────────────
            if self.message_queue.has_followup():
                followup_msgs = self.message_queue.get_followup_messages()
                pending_messages = [m.content for m in followup_msgs]
                continue  # 开启外层循环新一轮任务

            break  # 队列全清空，任务彻底完成

        await self._emit(
            AgentEnd(
                messages=list(self.messages),
                final_text=final_text,
                iterations=iteration,
                stop_reason="end_turn",
            )
        )
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

    async def compact(self, custom_instructions: str = "") -> None:
        """手动触发压缩：无条件执行一次 L4 摘要（写缓存 + 事件），不动 messages。"""
        await self._ctx.force_compact(self.messages)
        await self._handle_compaction()

    # ── 内部实现（run 循环辅助）──────────────────────────────

    def _llm_chat(self, messages, tools):
        """封装 llm.chat：透传 model（SDK 通用参数）。"""
        return self.llm.chat(messages=messages, tools=tools, model=self.model)

    async def _prepare_tool(
        self, tc: dict
    ) -> tuple[str, dict, str | None, HookResult | None]:
        """解析 JSON + ToolExecutionStart hook 阶段：返回 (name, args, 错误文本或 None, hook)。永不抛。"""
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, TypeError) as exc:
            return name, {}, f"Invalid JSON arguments for tool '{name}': {exc}", None

        try:
            hook = await self._emit(ToolExecutionStart(tc["id"], name, args))
        except Exception as exc:
            return (
                name,
                args,
                f"Error in ToolExecutionStart hook for '{name}': {exc}",
                None,
            )

        if isinstance(hook, HookResult) and hook.block:
            return name, args, f"Tool '{name}' blocked: {hook.reason}", hook
        if isinstance(hook, HookResult) and hook.updated_args is not None:
            args = hook.updated_args
        return name, args, None, hook

    async def _post_execute_hook(
        self, tc: dict, result: ToolResult
    ) -> tuple[str, bool]:
        """执行后处理阶段：ToolExecutionEnd hook 改写结果。永不抛。"""
        name = tc["function"]["name"]
        try:
            hook = await self._emit(
                ToolExecutionEnd(tc["id"], name, result.serialize(), not result.ok)
            )
        except Exception as exc:
            return f"Error in ToolExecutionEnd hook for '{name}': {exc}", True

        if isinstance(hook, HookResult) and hook.updated_result is not None:
            return hook.updated_result, False
        return result.serialize(), not result.ok

    async def _handle_compaction(self) -> None:
        """prepare/force_compact 触发压缩后：写回 session（桥）+ 事件。"""
        self._ctx_bridge.write_compaction(self._ctx)
        info = self._ctx.pending_compaction
        if info is not None:
            await self._emit(
                ContextCompacted(
                    tokens_before=info.tokens_before,
                    tokens_after=info.tokens_after,
                    summarized_count=info.summarized_count,
                )
            )

    async def _emit(self, event: Event) -> HookResult | None:
        """触发事件的所有 hook（委托 HookRegistry）。"""
        return await self.hooks.emit(event)
