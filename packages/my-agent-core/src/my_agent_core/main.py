"""demo 入口：跑三个固定问题，打印 ReAct 循环过程与最终答案。

运行：uv run python -m my_agent_core.main（在项目根目录执行，需要 .env 里的 OPENAI_API_KEY）
"""
from __future__ import annotations

import os
from datetime import datetime

from dotenv import load_dotenv
from my_agent_llm import Config, LLM

from my_agent_core.agent import run_agent
from my_agent_core.tools import tool

QUESTIONS = [
    "Use the multiply tool to calculate 37 times 19.",
    "What time is it now?",
    "What's the weather like in Tokyo and Paris?",
]


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
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


def main() -> None:
    load_dotenv()
    llm = build_llm()
    for question in QUESTIONS:
        print(f"\n=== 问题: {question} ===")
        answer = run_agent(
            question,
            tools=TOOLS,
            llm=llm,
            system_prompt=DEMO_SYSTEM_PROMPT,
        )
        print(f"\n最终答案: {answer}")


if __name__ == "__main__":
    main()
