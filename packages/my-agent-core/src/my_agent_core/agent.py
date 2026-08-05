"""ReAct 循环 —— 调度层。

模型调用 → 检查 tool_calls → 执行工具 → 观察结果写回消息 → 循环，
直到模型不再发起工具调用（经典退出条件：tool_calls 为空 → 结束）。

模型边界交给 my-agent-llm 的 LLM 门面；消息状态是 Message 对象列表。
"""
from __future__ import annotations

from my_agent_llm import LLM, Message

from my_agent_core.registry import ToolRegistry
from my_agent_core.tools import Tool


def run_agent(
    question: str,
    *,
    tools: list[Tool],
    llm: LLM,
    system_prompt: str | None = None,
) -> str:
    """运行 ReAct 循环，返回模型的最终文本回答。
    """
    # 无默认系统提示词：仅当调用方传入时才前置 system 消息
    messages: list[Message] = []
    if system_prompt is not None:
        messages.append(Message(role="system", content=system_prompt))
    messages.append(Message(role="user", content=question))
    # tools 注册表：execute 按 tool_call["function"]["name"] 在这里找到目标工具
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)
    # schemas = 请求的 tools 参数：全部工具的 JSON schema
    schemas = registry.get_schemas()

    iteration = 0
    while True:  # 无无限循环护栏：退出完全由模型自己判断
        iteration += 1
        # ── Reason：把完整消息历史 + 工具说明书发给模型。
        resp = llm.chat(messages=messages, tools=schemas)

        # 把模型的判断结果落盘进 messages（assistant 消息的 tool_calls 存 metadata）
        messages.append(
            Message(
                role="assistant",
                content=resp.content or "",
                metadata={"tool_calls": resp.tool_calls} if resp.tool_calls else None,
            )
        )

        # ── 经典退出条件：模型没有发起任何 tool_calls，
        #    说明它认为“可以直接回答了”——循环结束，返回文本。
        if not resp.tool_calls:
            print(f"[round {iteration}] 最终回答")
            return resp.content

        # ── Act + Observe：逐个执行本轮的全部 tool_calls（模型可能一轮发起多个），
        #    结果作为 tool 消息写回 messages——tool_call_id 与上面助手的调用配对。
        for tc in resp.tool_calls:
            print(
                f"[round {iteration}] 调用工具 "
                f"{tc['function']['name']}({tc['function']['arguments']})"
            )
            result = registry.execute(tc)  # 错误会被转成 ToolResult，不会抛异常
            observation = result.serialize()
            print(f"[round {iteration}] 观察: {observation}")
            messages.append(
                Message(
                    role="tool",
                    content=observation,
                    metadata={"tool_call_id": tc["id"]},
                )
            )
