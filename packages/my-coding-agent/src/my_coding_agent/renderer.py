"""事件流打字机与彩色 Diff 渲染器 (EventRenderer)。

单向只读消费 ReAct 循环事件，使用 rich 实现高颜值终端视觉流：
- 思考过程 (reasoning_content): dim italic 浅灰打字机流式呈现；
- 正文内容 (text / content): 正常打字机增量输出；
- 工具执行徽标: ⚙️  [tool_name] 与入参截断展示；
- 工具执行状态: ✓ OK / ✗ Failed，支持 edit 工具输出的 Unified Diff 语法高亮；
- 单轮结束: 统计耗时与推理回合。
"""

from __future__ import annotations

import re
import time
from typing import Any

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    Event,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
)
from pydantic import BaseModel
from rich.console import Console
from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text

__all__ = ["EventRenderer", "TextChunk"]


class TextChunk(BaseModel):
    """文本增量块，对齐 CLI 打字机与思考链协议。"""

    text: str = ""
    reasoning_content: str | None = None


class EventRenderer:
    """实时将 ReAct 循环事件渲染为精美终端视觉输出。"""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self._start_time: float = 0.0
        self._in_thinking: bool = False

    def on_event(self, event: Event) -> None:
        """事件驱动回调函数，消费生命周期事实并输出渲染。"""
        if isinstance(event, AgentStart):
            self._start_time = time.time()
            self._in_thinking = False

        elif isinstance(event, MessageUpdate):
            chunk: Any = event.chunk
            if chunk is not None:
                # 提取思考链增量：优先属性 reasoning_content，次选 metadata 中的 reasoning_content
                reasoning = getattr(chunk, "reasoning_content", None)
                if not reasoning and getattr(chunk, "metadata", None) and isinstance(chunk.metadata, dict):
                    reasoning = chunk.metadata.get("reasoning_content")

                # 提取正文增量：兼容 text 与 content
                text = getattr(chunk, "text", None) or getattr(chunk, "content", None)

                if reasoning:
                    if not self._in_thinking:
                        self.console.print("\n[dim]💭 思考过程:[/dim] ", end="")
                        self._in_thinking = True
                    self.console.print(Text(str(reasoning), style="dim italic"), end="")
                elif text:
                    if self._in_thinking:
                        self.console.print("\n")
                        self._in_thinking = False
                    self.console.print(str(text), end="", markup=False, highlight=False)

        elif isinstance(event, ToolExecutionStart):
            if self._in_thinking:
                self.console.print("\n")
                self._in_thinking = False
            args_str = ", ".join(f"{k}={repr(v)}" for k, v in event.args.items()) if event.args else ""
            if len(args_str) > 80:
                args_str = args_str[:77] + "..."
            self.console.print(
                f"\n[cyan]⚙️  \\[{escape(event.tool_name)}][/cyan] [dim]{escape(args_str)}[/dim]",
                highlight=False,
            )

        elif isinstance(event, ToolExecutionEnd):
            status = "[red]✗ Failed[/red]" if event.is_error else "[green]✓ OK[/green]"
            self.console.print(
                f"   {status} \\[{escape(event.tool_name)}]", highlight=False
            )

            res_str = str(event.result) if event.result is not None else ""
            # 提取并高亮 Diff
            if "```diff" in res_str:
                m = re.search(r"```diff\r?\n(.*?)(?:\r?\n)?```", res_str, re.DOTALL)
                if m:
                    diff_block = m.group(1)
                    syntax = Syntax(diff_block, "diff", theme="monokai", line_numbers=False)
                    self.console.print(syntax)

        elif isinstance(event, AgentEnd):
            if self._in_thinking:
                self.console.print("\n")
                self._in_thinking = False
            elapsed = time.time() - self._start_time if self._start_time > 0 else 0.0
            self.console.print(
                f"\n[dim]── 耗时: {elapsed:.1f}s | 回合: {event.iterations} ──[/dim]\n",
                highlight=False,
            )
