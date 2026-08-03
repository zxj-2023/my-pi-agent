"""ReAct 循环 —— 调度层。

模型调用 → 检查 tool_calls → 执行工具 → 观察结果写回消息 → 循环，
直到模型不再发起工具调用（经典退出条件：tool_calls 为空 → 结束）。

没有图、没有 Message 类——消息状态就是 OpenAI wire format 的普通 dict
列表，协议格式本身就是状态。
"""
from __future__ import annotations

from typing import Any

from my_agent_core.registry import ToolRegistry
from my_agent_core.tools import Tool


def run_agent(
    question: str,
    *,
    tools: list[Tool],
    client: Any,
    model: str,
    system_prompt: str | None = None,
) -> str:
    """运行 ReAct 循环，返回模型的最终文本回答。
    """
    # 无默认系统提示词：仅当调用方传入时才前置 system 消息
    messages: list[dict[str, Any]] = []
    if system_prompt is not None:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": question})
    # tools 注册表：execute 按 tool_call.function.name 在这里找到目标工具
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)
    # schemas = 请求的 tools 参数：全部工具的 JSON schema
    schemas = registry.get_schemas()

    iteration = 0
    while True:  # 无无限循环护栏：退出完全由模型自己判断
        iteration += 1
        # ── Reason：把完整消息历史 + 工具说明书发给模型。
        response = client.chat.completions.create(
            model=model, messages=messages, tools=schemas
        )
        msg = response.choices[0].message

        # 把模型的判断结果落盘进 messages
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content,
        }
        if msg.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_message)

        # ── 经典退出条件：模型没有发起任何 tool_calls，
        #    说明它认为“可以直接回答了”——循环结束，返回文本。
        if not msg.tool_calls:
            print(f"[round {iteration}] 最终回答")
            return msg.content

        # ── Act + Observe：逐个执行本轮的全部 tool_calls（模型可能一轮发起多个），
        #    结果作为 tool 消息写回 messages——tool_call_id 与上面助手的调用配对。
        #    随后循环回到 Reason：下一轮模型会看到这些观察结果，再次决策。
        for tc in msg.tool_calls:
            print(
                f"[round {iteration}] 调用工具 "
                f"{tc.function.name}({tc.function.arguments})"
            )
            observation = registry.execute(tc).serialize()  # 错误会被转成消息文本，不会抛异常
            print(f"[round {iteration}] 观察: {observation}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": observation,
                }
            )

