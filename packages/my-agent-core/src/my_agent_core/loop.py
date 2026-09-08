"""纯函数 ReAct 微内核 (loop.py) 与上下文清洗 (_provider_context)。

本模块将 ReAct 循环彻底解耦为无状态、可组合的异步生成器，外部宿主只需消费事件流。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from my_agent_llm import Message, StreamChunk

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
)
from my_agent_core.registry import ToolRegistry
from my_agent_core.tool_history import (
    _INTERRUPTED_TOOL_RESULT,
    repair_tool_history,
)
from my_agent_core.tools import ToolResult

# 事件类型别名，对齐规范
AgentEvent = Event


class CancellationToken:
    """协作式取消令牌，供宿主在流式过程中从外部主动请求安全中断。"""

    def __init__(self) -> None:
        self._cancelled: bool = False

    def is_cancelled(self) -> bool:
        """检查是否已请求取消。"""
        return self._cancelled

    def cancel(self) -> None:
        """触发协作式取消。"""
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        """取消状态属性访问捷径。"""
        return self._cancelled


def _provider_context(messages: Sequence[Message]) -> list[Message]:
    """清洗会话历史以严格满足主流大模型 Provider 的上下文契约。

    1. 剥离无正文且以异常中断结尾的终端 assistant 失败轮次（避免 OpenAI/Anthropic 400）；
    2. 串联 repair_tool_history 拓扑修复，自动补齐断头调用并安全丢弃孤儿结果。
    """
    replayable = tuple(
        m
        for m in messages
        if not (
            m.role == "assistant"
            and bool(
                m.metadata and m.metadata.get("stop_reason") in {"error", "aborted"}
            )
            and not m.content
        )
    )
    return list(repair_tool_history(replayable).messages)


async def run_agent_loop(
    *,
    llm: Any,
    messages: list[Message],
    tools: ToolRegistry | Sequence[Any] | None = None,
    context_manager: Any | None = None,
    model: str | None = None,
    system: str = "",
    prompts: Sequence[Message | str] = (),
    max_turns: int | None = None,
    max_iterations: int | None = None,
    signal: CancellationToken | None = None,
    get_steering_messages: Callable[[], Sequence[Message | str]] | None = None,
    get_follow_up_messages: Callable[[], Sequence[Message | str]] | None = None,
    hook_registry: HookRegistry | None = None,
) -> AsyncIterator[Event]:
    """执行 ReAct 双层事件循环，逐一 yield 出生命周期事件。

    内层循环处理微观单任务 ReAct 工具调用与 steering 即时转向；
    外层循环处理宏观 follow-up 任务收割。
    """
    if isinstance(tools, ToolRegistry):
        registry = tools
    elif isinstance(tools, (list, tuple)):
        registry = ToolRegistry()
        for t in tools:
            registry.register(t)
    else:
        registry = ToolRegistry()

    effective_max = max_turns if max_turns is not None else max_iterations

    # 初始化协作取消检查
    if signal is not None and signal.is_cancelled():
        end_ev = AgentEnd(
            messages=list(messages),
            final_text=None,
            iterations=0,
            stop_reason="cancelled",
        )
        yield end_ev
        if hook_registry is not None:
            await hook_registry.emit(end_ev)
        return

    # system prompt 初始化
    if system:
        if not messages or messages[0].role != "system":
            messages.insert(0, Message(role="system", content=system))
        else:
            system = messages[0].content
    elif messages and messages[0].role == "system":
        system = messages[0].content

    # prompts 规范化
    converted_prompts: list[Message] = []
    for p in prompts:
        if isinstance(p, Message):
            converted_prompts.append(p)
        elif isinstance(p, str):
            converted_prompts.append(Message(role="user", content=p))

    if converted_prompts:
        user_input = converted_prompts[0].content
    else:
        user_input = ""
        for m in reversed(messages):
            if m.role == "user":
                user_input = m.content
                break

    # 派发 AgentStart
    start_event = AgentStart(system_prompt=system, user_input=user_input)
    yield start_event
    if hook_registry is not None:
        start_hook = await hook_registry.emit(start_event)
        if isinstance(start_hook, HookResult):
            if start_hook.block:
                reason = f": {start_hook.reason}" if start_hook.reason else ""
                end_ev = AgentEnd(
                    messages=list(messages),
                    final_text=f"(blocked{reason})",
                    iterations=0,
                    stop_reason="blocked",
                )
                yield end_ev
                await hook_registry.emit(end_ev)
                return
            if start_hook.updated_system_prompt is not None:
                system = start_hook.updated_system_prompt
                if messages and messages[0].role == "system":
                    messages[0] = Message(role="system", content=system)
                else:
                    messages.insert(0, Message(role="system", content=system))

    # 将初始 prompts 注入 messages 并派发消息事件
    for p_msg in converted_prompts:
        messages.append(p_msg)
        s_ev = MessageStart(p_msg)
        yield s_ev
        if hook_registry is not None:
            await hook_registry.emit(s_ev)
        e_ev = MessageEnd(p_msg)
        yield e_ev
        if hook_registry is not None:
            await hook_registry.emit(e_ev)

    pending_messages: list[Message] = []
    if get_steering_messages is not None:
        init_steer = get_steering_messages()
        if init_steer:
            pending_messages.extend(
                [
                    Message(role="user", content=m) if isinstance(m, str) else m
                    for m in init_steer
                ]
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

            if signal is not None and signal.is_cancelled():
                end_ev = AgentEnd(
                    messages=list(messages),
                    final_text=final_text,
                    iterations=iteration,
                    stop_reason="cancelled",
                )
                yield end_ev
                if hook_registry is not None:
                    await hook_registry.emit(end_ev)
                return

            if effective_max is not None and iteration > effective_max:
                end_ev = AgentEnd(
                    messages=list(messages),
                    final_text=final_text,
                    iterations=iteration,
                    stop_reason="max_iterations",
                )
                yield end_ev
                if hook_registry is not None:
                    await hook_registry.emit(end_ev)
                return

            turn_start_ev = TurnStart(iteration)
            yield turn_start_ev
            if hook_registry is not None:
                await hook_registry.emit(turn_start_ev)

            # Turn 起始点注入 pending 消息
            if pending_messages:
                for p_msg in pending_messages:
                    messages.append(p_msg)
                    s_ev = MessageStart(p_msg)
                    yield s_ev
                    if hook_registry is not None:
                        await hook_registry.emit(s_ev)
                    e_ev = MessageEnd(p_msg)
                    yield e_ev
                    if hook_registry is not None:
                        await hook_registry.emit(e_ev)
                pending_messages = []

            # 前置清洗与上下文准备
            clean_messages = _provider_context(messages)
            if context_manager is not None:
                view = await context_manager.prepare(clean_messages)
            else:
                view = clean_messages

            # 决策点: BeforeModelCall
            before_call_ev = BeforeModelCall(messages=list(view), iteration=iteration)
            yield before_call_ev
            if hook_registry is not None:
                ctx_hook = await hook_registry.emit(before_call_ev)
                if isinstance(ctx_hook, HookResult):
                    if ctx_hook.block:
                        reason = f": {ctx_hook.reason}" if ctx_hook.reason else ""
                        end_ev = AgentEnd(
                            messages=list(messages),
                            final_text=f"(blocked{reason})",
                            iterations=iteration,
                            stop_reason="blocked",
                        )
                        yield end_ev
                        await hook_registry.emit(end_ev)
                        return
                    if ctx_hook.updated_messages is not None:
                        view = ctx_hook.updated_messages

            # 驱动 LLM 调用与流式捕获
            tool_schemas = registry.get_schemas()
            content_acc = ""
            final_tool_calls = None
            last_usage = None
            cancelled = False

            if hasattr(llm, "achat_stream"):
                stream = llm.achat_stream(
                    messages=view, tools=tool_schemas, model=model
                )
                async for chunk in stream:
                    if chunk.content:
                        content_acc += chunk.content
                    if getattr(chunk, "tool_calls", None):
                        final_tool_calls = chunk.tool_calls
                    if getattr(chunk, "usage", None):
                        last_usage = chunk.usage

                    if signal is not None and signal.is_cancelled():
                        cancelled = True
                        break

                    update_ev = MessageUpdate(
                        message=Message(role="assistant", content=content_acc),
                        chunk=chunk,
                    )
                    yield update_ev
                    if hook_registry is not None:
                        hook = await hook_registry.emit(update_ev)
                        if isinstance(hook, HookResult) and hook.block:
                            cancelled = True
                            break
                    if signal is not None and signal.is_cancelled():
                        cancelled = True
                        break
            elif hasattr(llm, "achat"):
                resp = await llm.achat(messages=view, tools=tool_schemas, model=model)
                content_acc = resp.content or ""
                final_tool_calls = resp.tool_calls
                last_usage = resp.usage
                chunk = StreamChunk(
                    content=content_acc,
                    tool_calls=final_tool_calls,
                    usage=last_usage,
                )
                update_ev = MessageUpdate(
                    message=Message(role="assistant", content=content_acc),
                    chunk=chunk,
                )
                yield update_ev
                if hook_registry is not None:
                    hook = await hook_registry.emit(update_ev)
                    if isinstance(hook, HookResult) and hook.block:
                        cancelled = True
                if signal is not None and signal.is_cancelled():
                    cancelled = True
            else:
                resp = llm.chat(messages=view, tools=tool_schemas, model=model)
                content_acc = resp.content or ""
                final_tool_calls = resp.tool_calls
                last_usage = resp.usage
                chunk = StreamChunk(
                    content=content_acc,
                    tool_calls=final_tool_calls,
                    usage=last_usage,
                )
                update_ev = MessageUpdate(
                    message=Message(role="assistant", content=content_acc),
                    chunk=chunk,
                )
                yield update_ev
                if hook_registry is not None:
                    hook = await hook_registry.emit(update_ev)
                    if isinstance(hook, HookResult) and hook.block:
                        cancelled = True
                if signal is not None and signal.is_cancelled():
                    cancelled = True

            # 中途取消处理与断头补齐
            if cancelled or (signal is not None and signal.is_cancelled()):
                if final_tool_calls:
                    assistant = Message(
                        role="assistant",
                        content=content_acc,
                        metadata={"tool_calls": final_tool_calls},
                    )
                    messages.append(assistant)
                    s_ev = MessageStart(assistant)
                    yield s_ev
                    if hook_registry is not None:
                        await hook_registry.emit(s_ev)
                    e_ev = MessageEnd(assistant)
                    yield e_ev
                    if hook_registry is not None:
                        await hook_registry.emit(e_ev)

                    for tc in final_tool_calls:
                        synth = Message(
                            role="tool",
                            content=_INTERRUPTED_TOOL_RESULT,
                            metadata={"tool_call_id": tc["id"], "is_error": True},
                        )
                        messages.append(synth)
                        s_ev = MessageStart(synth)
                        yield s_ev
                        if hook_registry is not None:
                            await hook_registry.emit(s_ev)
                        e_ev = MessageEnd(synth)
                        yield e_ev
                        if hook_registry is not None:
                            await hook_registry.emit(e_ev)

                end_ev = AgentEnd(
                    messages=list(messages),
                    final_text=None,
                    iterations=iteration,
                    stop_reason="cancelled",
                )
                yield end_ev
                if hook_registry is not None:
                    await hook_registry.emit(end_ev)
                return

            if (
                last_usage
                and context_manager is not None
                and hasattr(context_manager, "record_usage")
            ):
                context_manager.record_usage(last_usage)

            if (
                context_manager is not None
                and getattr(context_manager, "pending_compaction", None) is not None
            ):
                info = context_manager.pending_compaction
                compact_ev = ContextCompacted(
                    tokens_before=info.tokens_before,
                    tokens_after=info.tokens_after,
                    summarized_count=info.summarized_count,
                )
                yield compact_ev
                if hook_registry is not None:
                    await hook_registry.emit(compact_ev)

            assistant = Message(
                role="assistant",
                content=content_acc,
                metadata={"tool_calls": final_tool_calls} if final_tool_calls else None,
            )
            messages.append(assistant)
            s_ev = MessageStart(assistant)
            yield s_ev
            if hook_registry is not None:
                await hook_registry.emit(s_ev)
            e_ev = MessageEnd(assistant)
            yield e_ev
            if hook_registry is not None:
                await hook_registry.emit(e_ev)

            # 工具执行阶段
            if final_tool_calls:
                if signal is not None and signal.is_cancelled():
                    for tc in final_tool_calls:
                        synth = Message(
                            role="tool",
                            content=_INTERRUPTED_TOOL_RESULT,
                            metadata={"tool_call_id": tc["id"], "is_error": True},
                        )
                        messages.append(synth)
                        s_ev = MessageStart(synth)
                        yield s_ev
                        if hook_registry is not None:
                            await hook_registry.emit(s_ev)
                        e_ev = MessageEnd(synth)
                        yield e_ev
                        if hook_registry is not None:
                            await hook_registry.emit(e_ev)

                    end_ev = AgentEnd(
                        messages=list(messages),
                        final_text=None,
                        iterations=iteration,
                        stop_reason="cancelled",
                    )
                    yield end_ev
                    if hook_registry is not None:
                        await hook_registry.emit(end_ev)
                    return

                tool_call_dicts = final_tool_calls
                prepared_calls: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
                direct_observations: dict[int, ToolResult] = {}

                for idx, tc in enumerate(tool_call_dicts):
                    tc_id = tc.get("id", "")
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    raw_args = func.get("arguments", "{}")
                    try:
                        if isinstance(raw_args, str):
                            args = json.loads(raw_args)
                        else:
                            args = raw_args or {}
                        err = None
                    except (json.JSONDecodeError, TypeError) as exc:
                        args = {}
                        err = f"Invalid JSON arguments for tool '{name}': {exc}"

                    start_tool_ev = ToolExecutionStart(tc_id, name, args)
                    yield start_tool_ev

                    if hook_registry is not None:
                        try:
                            hook = await hook_registry.emit(start_tool_ev)
                            if isinstance(hook, HookResult) and hook.block:
                                err = f"Tool '{name}' blocked: {hook.reason}"
                            elif (
                                isinstance(hook, HookResult)
                                and hook.updated_args is not None
                            ):
                                args = hook.updated_args
                        except Exception as exc:
                            err = (
                                f"Error in ToolExecutionStart hook for '{name}': {exc}"
                            )

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
                    batch_results = await registry.execute_batch(call_dicts_to_run)

                    for (idx, _tc), res in zip(
                        effective_calls, batch_results, strict=False
                    ):
                        _tc_id = _tc.get("id", "")
                        _name = _tc.get("function", {}).get("name", "")
                        obs_str = res.serialize()
                        is_err = not res.ok

                        end_tool_ev = ToolExecutionEnd(_tc_id, _name, obs_str, is_err)
                        yield end_tool_ev

                        if hook_registry is not None:
                            try:
                                hook = await hook_registry.emit(end_tool_ev)
                                if (
                                    isinstance(hook, HookResult)
                                    and hook.updated_result is not None
                                ):
                                    obs_str = hook.updated_result
                                    is_err = False
                            except Exception as exc:
                                obs_str = f"Error in ToolExecutionEnd hook for '{_name}': {exc}"
                                is_err = True

                        direct_observations[idx] = (
                            ToolResult(ok=not is_err, data=obs_str)
                            if not is_err
                            else ToolResult(ok=False, error=obs_str)
                        )

                tool_results: list[Message] = []
                for idx, tc in enumerate(tool_call_dicts):
                    res = direct_observations[idx]
                    observation = res.serialize()
                    tool_msg = Message(
                        role="tool",
                        content=observation,
                        metadata={"tool_call_id": tc["id"]},
                    )
                    messages.append(tool_msg)
                    s_ev = MessageStart(tool_msg)
                    yield s_ev
                    if hook_registry is not None:
                        await hook_registry.emit(s_ev)
                    e_ev = MessageEnd(tool_msg)
                    yield e_ev
                    if hook_registry is not None:
                        await hook_registry.emit(e_ev)
                    tool_results.append(tool_msg)

                has_more_tool_calls = True
            else:
                tool_results = []
                has_more_tool_calls = False
                final_text = content_acc

            turn_end_ev = TurnEnd(message=assistant, tool_results=tool_results)
            yield turn_end_ev
            if hook_registry is not None:
                await hook_registry.emit(turn_end_ev)

            # 消费 steering messages
            if get_steering_messages is not None:
                steer_msgs = get_steering_messages()
                if steer_msgs:
                    pending_messages = [
                        Message(role="user", content=m) if isinstance(m, str) else m
                        for m in steer_msgs
                    ]

        # 消费 follow-up messages
        if get_follow_up_messages is not None:
            followup_msgs = get_follow_up_messages()
            if followup_msgs:
                pending_messages = [
                    Message(role="user", content=m) if isinstance(m, str) else m
                    for m in followup_msgs
                ]
                continue

        break

    agent_end_ev = AgentEnd(
        messages=list(messages),
        final_text=final_text,
        iterations=iteration,
        stop_reason="end_turn",
    )
    yield agent_end_ev
    if hook_registry is not None:
        await hook_registry.emit(agent_end_ev)
