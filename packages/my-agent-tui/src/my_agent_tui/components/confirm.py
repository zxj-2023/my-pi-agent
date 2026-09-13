"""轻量终端交互审查确认组件 ConfirmView。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from rich.console import Console
from rich.panel import Panel

from my_agent_tui.diff import render_diff_with_word_highlight


class ConfirmView:
    """对标 Pig-Mono 的轻量终端交互审查确认组件。"""

    def __init__(
        self,
        console: Console | None = None,
        input_hook: Callable[[str], Awaitable[str]] | None = None,
    ):
        self.console = console or Console()
        self.input_hook = input_hook

    async def prompt_confirm(
        self,
        prompt_text: str,
        default: bool = True,
        details_text: str | None = None,
        title: str = "⚠️  操作安全审查",
    ) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"

        # 展示详情面板（如 Diff 或 Shell 命令）
        if details_text:
            if "--- " in details_text and "+++ " in details_text:
                rendered_details = render_diff_with_word_highlight(details_text)
            else:
                rendered_details = details_text
            self.console.print(Panel(rendered_details, title=title, border_style="yellow"))

        prompt_str = f"[bold yellow]{prompt_text}[/bold yellow] {suffix}: "

        if self.input_hook:
            raw_ans = await self.input_hook(prompt_str)
        else:
            try:
                # 异步兼容的控制台读取
                loop = asyncio.get_running_loop()
                raw_ans = await loop.run_in_executor(None, lambda: input(f"{prompt_text} {suffix}: "))
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[red]已取消操作。[/red]")
                return False

        ans = raw_ans.strip().lower()
        if not ans:
            return default
        return ans in ("y", "yes", "true", "1")
