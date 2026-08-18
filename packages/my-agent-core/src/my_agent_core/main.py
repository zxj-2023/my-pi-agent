"""demo 入口：跑三个固定问题，展示原生异步 ReAct 循环、流式打字机与并发工具执行。

运行：uv run python -m my_agent_core.main（在项目根目录执行，需要 .env 里的 OPENAI_API_KEY）
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from my_agent_llm import LLM, Config  # pyright: ignore[reportMissingImports]

from my_agent_core.agent import Agent
from my_agent_core.events import (
    AgentEnd,
    HookResult,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnStart,
)
from my_agent_core.session_store import SessionStore
from my_agent_core.tools import tool

QUESTIONS = [
    "Use the multiply tool to calculate 37 times 19.",
    "What time is it now?",
    "What's the weather like in Tokyo and Paris?",
]


@tool(is_parallel_safe=True)
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool(is_parallel_safe=True)
def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool(is_parallel_safe=True)
def get_weather(city: str) -> str:
    """Get the weather for a city (simulated data)."""
    return f"{city}: sunny, 22°C (simulated)"


TOOLS = [multiply, get_current_time, get_weather]

# 演示层的系统提示词：my_agent_core 库层没有默认值，
# 给什么提示词是应用层（本 demo）的选择。
DEMO_SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the available tools when they help; "
    "answer directly when they don't."
)


def print_events(event) -> HookResult | None:
    """把循环事件打印成 demo 过程输出（Agent 不内置 print，输出是应用层的选择）。"""
    if isinstance(event, TurnStart):
        print(f"\n[round {event.iteration}]")
    elif isinstance(event, MessageUpdate):
        # 流式 Token 打字机增量打印
        if event.chunk and getattr(event.chunk, "delta", None):
            sys.stdout.write(event.chunk.delta)
            sys.stdout.flush()
    elif isinstance(event, ToolExecutionStart):
        print(f"\n  [Tool] {event.tool_name}({event.args})")
    elif isinstance(event, ToolExecutionEnd):
        print(f"  [Obs] {event.result}")
    elif isinstance(event, AgentEnd):
        print(f"\n[End] stop_reason={event.stop_reason}, iterations={event.iterations}")
    return None  # 纯观察，不干预


def build_llm() -> LLM:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to .env.")
    options: dict[str, str] = {"provider": "openai", "api_key": api_key}
    if base_url := os.getenv("OPENAI_BASE_URL"):
        options["base_url"] = base_url
    if model := os.getenv("OPENAI_MODEL"):
        options["model"] = model
    return LLM(config=Config(**options))


async def amain() -> None:
    load_dotenv()
    llm = build_llm()
    store = SessionStore()  # 默认 workspace=cwd
    for question in QUESTIONS:
        print(f"\n{'=' * 20} 问题: {question} {'=' * 20}")
        session = store.create()
        agent = Agent(
            llm=llm,
            tools=TOOLS,
            session=session,
            system_prompt=DEMO_SYSTEM_PROMPT,
            hooks=[
                (TurnStart, print_events),
                (MessageUpdate, print_events),
                (ToolExecutionStart, print_events),
                (ToolExecutionEnd, print_events),
                (AgentEnd, print_events),
            ],
        )
        answer = await agent.run(question)
        if answer is None:
            print("（达到 max_iterations 上限，未得到最终回答）")


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
