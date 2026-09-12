from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from my_coding_agent.agent import CodingAgent


@dataclass
class CommandContext:
    agent: CodingAgent
    raw_args: str
    console: Console


class CommandDispatcher:
    """产品层斜杠命令分发路由中枢。"""

    def __init__(self, agent: CodingAgent):
        self.agent = agent
        self.exit_requested: bool = False
        self._handlers: dict[str, tuple[Callable[[CommandContext], Any], str]] = {}
        self._register_builtins()

    def register(
        self,
        name: str,
        handler: Callable[[CommandContext], Any],
        description: str = "",
    ) -> None:
        self._handlers[name.lstrip("/")] = (handler, description)

    async def dispatch(self, text: str, console: Console) -> bool:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return False

        parts = stripped[1:].strip().split(maxsplit=1)
        if not parts or not parts[0]:
            return False

        cmd_name = parts[0].lower()
        raw_args = parts[1] if len(parts) > 1 else ""

        if cmd_name in self._handlers:
            handler, _ = self._handlers[cmd_name]
            ctx = CommandContext(agent=self.agent, raw_args=raw_args, console=console)
            res = handler(ctx)
            if inspect.isawaitable(res):
                await res
            return True

        console.print(f"[red]未知命令: /{cmd_name}。输入 /help 查看可用命令。[/red]")
        return True

    def _register_builtins(self) -> None:
        self.register("help", self._cmd_help, "显示所有可用命令及说明")
        self.register("clear", self._cmd_clear, "清空终端屏幕")
        self.register("undo", self._cmd_undo, "撤销上一轮对话修改 (session.rewind)")
        self.register("compact", self._cmd_compact, "手动触发上下文智能压缩")
        self.register("session", self._cmd_session, "查看当前会话状态与 Token 统计")
        self.register("tasks", self._cmd_tasks, "查看项目 TaskStore 待办看板")
        self.register("mcp", self._cmd_mcp, "查看已挂载的 MCP 服务器与工具")
        self.register("exit", self._cmd_exit, "退出当前交互式会话")
        self.register("quit", self._cmd_exit, "退出当前交互式会话")

    async def _cmd_help(self, ctx: CommandContext) -> None:
        table = Table(
            title="my-coding-agent 可用命令",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("命令", style="green", width=15)
        table.add_column("说明", style="dim")
        for name, (_, desc) in sorted(self._handlers.items()):
            table.add_row(f"/{name}", desc)
        ctx.console.print(table)

    async def _cmd_clear(self, ctx: CommandContext) -> None:
        ctx.console.clear()

    async def _cmd_undo(self, ctx: CommandContext) -> None:
        session = self.agent.session
        path = session.tree.get_current_path()
        if len(path) <= 1:
            ctx.console.print("[yellow]已经是会话最初状态，无法撤销。[/yellow]")
            return

        target_rewind_id = None
        for entry in reversed(path):
            role = getattr(entry, "role", None) or getattr(getattr(entry, "message", None), "role", None)
            if role == "user":
                target_rewind_id = entry.parent_id
                break

        if target_rewind_id is None:
            ctx.console.print("[yellow]未找到可回退的用户交互节点。[/yellow]")
            return

        try:
            session.rewind(target_rewind_id)
            if hasattr(self.agent, "agent") and hasattr(self.agent.agent, "_init_messages"):
                self.agent.agent.messages = self.agent.agent._init_messages(
                    session, getattr(self.agent.agent, "_system_prompt", None)
                )
            ctx.console.print(f"[green]↺ 已成功回退至节点 [{target_rewind_id[:8]}]，上一轮对话已安全撤销。[/green]")
        except Exception as e:
            ctx.console.print(f"[red]撤销失败: {e}[/red]")

    async def _cmd_compact(self, ctx: CommandContext) -> None:
        ctx.console.print("[cyan]⚙️ 正在执行 L4 智能上下文压缩...[/cyan]")
        try:
            res = await self.agent.compact()
            saved = getattr(res, "tokens_before", "OK") if res is not None else "OK"
            ctx.console.print(f"[green]✓ 上下文压缩完成！摘要节约 Token: {saved}[/green]")
        except Exception as e:
            ctx.console.print(f"[red]压缩失败: {e}[/red]")

    async def _cmd_session(self, ctx: CommandContext) -> None:
        s = self.agent.session
        sid = getattr(s, "session_id", getattr(s, "id", "unknown"))
        ctx.console.print(f"[bold]会话 ID:[/bold] {sid}")
        ctx.console.print(f"[bold]持久化路径:[/bold] {s.path}")
        ctx.console.print(f"[bold]消息总节点:[/bold] {len(s.tree.get_current_path())}")

    async def _cmd_tasks(self, ctx: CommandContext) -> None:
        ts = self.agent.task_store
        if not ts:
            ctx.console.print("[yellow]当前会话未启用 TaskStore 任务看板。[/yellow]")
            return
        tasks: list[Any] = []
        if hasattr(ts, "list"):
            tasks = list(ts.list())
        elif hasattr(ts, "list_tasks"):
            tasks = list(getattr(ts, "list_tasks")())
        if not tasks:
            ctx.console.print("[dim]当前没有待办任务。[/dim]")
            return
        table = Table(title="TaskStore 任务看板", show_header=True)
        table.add_column("ID", width=6)
        table.add_column("状态", width=12)
        table.add_column("主题", style="bold")
        for t in tasks:
            st_style = "green" if t.status == "completed" else "yellow" if t.status == "in_progress" else "dim"
            table.add_row(str(t.id), f"[{st_style}]{t.status}[/{st_style}]", t.subject)
        ctx.console.print(table)

    async def _cmd_mcp(self, ctx: CommandContext) -> None:
        registry = getattr(self.agent.agent, "registry", None)
        tools = registry._tools.values() if registry and hasattr(registry, "_tools") else []
        mcp_tools = [t for t in tools if getattr(t, "is_mcp", False)]
        ctx.console.print(f"[bold]已挂载 MCP 工具数:[/bold] {len(mcp_tools)}")
        for t in mcp_tools:
            ctx.console.print(f"  • [cyan]{t.name}[/cyan]: {t.description}")

    async def _cmd_exit(self, ctx: CommandContext) -> None:
        self.exit_requested = True
        ctx.console.print("[dim]正在退出... 再见！[/dim]")
