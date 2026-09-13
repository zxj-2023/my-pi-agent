from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from rich.console import Console
from rich.table import Table

from my_agent_llm.auth import antigravity as antigravity_auth
from my_agent_llm.auth import quota as quota_auth
from my_agent_llm.auth.antigravity import AntigravityCredentials
from my_agent_llm.config import Config

if TYPE_CHECKING:
    from my_coding_agent.agent import CodingAgent

SLASH_COMMANDS: list[str] = [
    "/help",
    "/clear",
    "/undo",
    "/compact",
    "/session",
    "/tasks",
    "/mcp",
    "/quota",
    "/model",
    "/mode",
    "/login",
    "/steer",
    "/followup",
    "/exit",
    "/quit",
]

COMMAND_HELP: dict[str, str] = {
    "/help": "显示所有可用命令及说明",
    "/clear": "清空终端屏幕",
    "/undo": "撤销上一轮对话修改 (session.rewind)",
    "/compact": "手动触发上下文智能压缩",
    "/session": "查看当前会话状态与 Token 统计",
    "/tasks": "查看项目 TaskStore 待办看板",
    "/mcp": "查看已挂载的 MCP 服务器与工具",
    "/quota": "查询 Google Antigravity 模型剩余配额与重置时间",
    "/login": "自省并连接 Antigravity 等本地 OAuth 鉴权凭据",
    "/model": "查看或即时热切换当前 Agent 底层模型",
    "/mode": "查看或切换当前权限模式 (review/yolo/strict/autonomous)",
    "/steer": "注入即时转向指令（在下一个安全点打断/干预模型执行）",
    "/followup": "追加排队追问指令（在当前轮次彻底完成后自动执行）",
    "/exit": "退出当前交互式会话",
    "/quit": "退出当前交互式会话",
}

for _k, _v in list(COMMAND_HELP.items()):
    if _k.startswith("/"):
        COMMAND_HELP[_k.lstrip("/")] = _v


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
        self._handlers[name.lstrip("/").lower()] = (handler, description)

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
            try:
                res = handler(ctx)
                if inspect.isawaitable(res):
                    await res
            except Exception as exc:
                console.print(f"[red]执行命令 /{cmd_name} 失败: {exc}[/red]")
            return True

        console.print(f"[red]未知命令: /{cmd_name}。输入 /help 查看可用命令。[/red]")
        return True

    def _register_builtins(self) -> None:
        self.register("help", self._cmd_help, COMMAND_HELP.get("help", "显示所有可用命令及说明"))
        self.register("clear", self._cmd_clear, COMMAND_HELP.get("clear", "清空终端屏幕"))
        self.register("undo", self._cmd_undo, COMMAND_HELP.get("undo", "撤销上一轮对话修改 (session.rewind)"))
        self.register("compact", self._cmd_compact, COMMAND_HELP.get("compact", "手动触发上下文智能压缩"))
        self.register("session", self._cmd_session, COMMAND_HELP.get("session", "查看当前会话状态与 Token 统计"))
        self.register("tasks", self._cmd_tasks, COMMAND_HELP.get("tasks", "查看项目 TaskStore 待办看板"))
        self.register("mcp", self._cmd_mcp, COMMAND_HELP.get("mcp", "查看已挂载的 MCP 服务器与工具"))
        self.register("quota", self._cmd_quota, COMMAND_HELP.get("quota", "查询 Google Antigravity 模型剩余配额与重置时间"))
        self.register("login", self._cmd_login, COMMAND_HELP.get("login", "自省并连接 Antigravity 等本地 OAuth 鉴权凭据"))
        self.register("model", self._cmd_model, COMMAND_HELP.get("model", "查看或即时热切换当前 Agent 底层模型"))
        self.register("mode", self._cmd_mode, COMMAND_HELP.get("mode", "查看或切换当前权限模式 (review/yolo/strict/autonomous)"))
        self.register("steer", self._cmd_steer, COMMAND_HELP.get("steer", "注入即时转向指令（在下一个安全点打断/干预模型执行）"))
        self.register("followup", self._cmd_followup, COMMAND_HELP.get("followup", "追加排队追问指令（在当前轮次彻底完成后自动执行）"))
        self.register("exit", self._cmd_exit, COMMAND_HELP.get("exit", "退出当前交互式会话"))
        self.register("quit", self._cmd_exit, COMMAND_HELP.get("quit", "退出当前交互式会话"))

    async def _cmd_help(self, ctx: CommandContext) -> None:
        table = Table(
            title="my-agent-tui 可用命令",
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

        user_found = False
        target_rewind_id = None
        for entry in reversed(path):
            role = getattr(entry, "role", None) or getattr(getattr(entry, "message", None), "role", None)
            if role == "user":
                user_found = True
                target_rewind_id = entry.parent_id
                break

        if not user_found:
            ctx.console.print("[yellow]未找到可回退的用户交互节点。[/yellow]")
            return

        if target_rewind_id is None:
            # 找到首轮 user entry，其 parent_id 为 None，说明回退将重置至会话最初空白状态
            try:
                if hasattr(self.agent, "agent") and hasattr(self.agent.agent, "reset"):
                    self.agent.agent.reset()
                else:
                    session.reset()
                    if hasattr(self.agent, "agent") and hasattr(self.agent.agent, "_init_messages"):
                        self.agent.agent.messages = self.agent.agent._init_messages(
                            session, getattr(self.agent.agent, "_system_prompt", None)
                        )
                ctx.console.print("[green]↺ 已成功回退至会话最初状态，上一轮对话已安全撤销。[/green]")
                return
            except Exception as e:
                ctx.console.print(f"[red]撤销失败: {e}[/red]")
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
            pending = getattr(getattr(self.agent, "agent", None), "_ctx", None)
            info = getattr(pending, "pending_compaction", None)
            if info and hasattr(info, "tokens_before") and hasattr(info, "tokens_after"):
                saved = f"{info.tokens_before - info.tokens_after} Tokens ({info.tokens_before} -> {info.tokens_after})"
            else:
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
        tools: list[Any] = []
        if registry is not None:
            if hasattr(registry, "list") and callable(registry.list):
                tools = list(registry.list())
            elif hasattr(registry, "_tools"):
                tools = list(registry._tools.values())
        mcp_tools = [t for t in tools if getattr(t, "is_mcp", False)]
        ctx.console.print(f"[bold]已挂载 MCP 工具数:[/bold] {len(mcp_tools)}")
        for t in mcp_tools:
            ctx.console.print(f"  • [cyan]{t.name}[/cyan]: {t.description}")

    async def _cmd_quota(self, ctx: CommandContext) -> None:
        ctx.console.print("[cyan]⚙️  正在查询 Antigravity 模型配额余量...[/cyan]", highlight=False)
        resolver = antigravity_auth.AntigravityAuthResolver()
        creds = resolver.resolve_credentials_raw()
        if creds is None:
            creds = AntigravityCredentials(access_token="")

        try:
            buckets = quota_auth.retrieve_user_quota_summary(creds)
        except Exception as e:
            ctx.console.print(f"[red]查询配额失败: {e}[/red]", highlight=False)
            return

        if not buckets:
            ctx.console.print(
                "[yellow]未能获取到配额信息，请确认已通过 /login antigravity 登录或配置有效凭据。[/yellow]",
                highlight=False,
            )
            return

        table = Table(
            title="Google Antigravity 模型配额余量",
            show_header=True,
            header_style="bold cyan",
            highlight=False,
        )
        table.add_column("模型 / 配额项", style="bold")
        table.add_column("剩余配额", justify="right")
        table.add_column("重置时间", style="dim")

        for b in buckets:
            pct = b.remaining_percent
            if pct >= 50:
                pct_style = "green"
            elif pct >= 20:
                pct_style = "yellow"
            else:
                pct_style = "red"

            filled_bars = int(round(pct / 10))
            empty_bars = 10 - filled_bars
            bar_visual = f"[{pct_style}]{'█' * filled_bars}{'░' * empty_bars}[/{pct_style}]"

            remaining_str = f"{bar_visual} [{pct_style}]{pct}%[/{pct_style}]"
            reset_time_str = b.reset_time if b.reset_time else "-"
            table.add_row(b.display_name or b.bucket_id, remaining_str, reset_time_str)

        ctx.console.print(table)

    async def _cmd_login(self, ctx: CommandContext) -> None:
        provider = ctx.raw_args.strip().lower()
        if not provider:
            ctx.console.print("[dim]用法: /login antigravity[/dim]", highlight=False)
            return

        if provider not in ("antigravity", "google-antigravity"):
            ctx.console.print(
                f"[yellow]暂不支持为提供商 '{provider}' 进行交互登录。目前支持: antigravity[/yellow]",
                highlight=False,
            )
            return

        resolver = antigravity_auth.AntigravityAuthResolver()
        creds = resolver.resolve_credentials_raw()
        if creds is None:
            ctx.console.print(
                f"[yellow]未在本地检测到 Antigravity 鉴权凭据。[/yellow]\n"
                f"[dim]请确保本地存在 {resolver.pi_auth_path} 或 {resolver.credentials_path}，"
                f"或设置 ANTIGRAVITY_ACCESS_TOKEN 环境变量。[/dim]",
                highlight=False,
            )
            return

        if resolver.is_expired(creds):
            if creds.refresh_token:
                ctx.console.print("[cyan]⚙️  检测到凭据已过期，正在尝试静默刷新...[/cyan]", highlight=False)
                try:
                    creds = resolver.refresh(creds)
                    ctx.console.print("[green]✓ Antigravity 凭据已成功刷新！[/green]", highlight=False)
                except Exception as e:
                    ctx.console.print(f"[red]刷新 Antigravity 凭据失败: {e}[/red]", highlight=False)
                    return
            else:
                ctx.console.print(
                    "[yellow]! Antigravity 凭据已过期且无可用的 refresh_token。[/yellow]", highlight=False
                )
                return

        source = creds.auth_file_path.name if creds.auth_file_path else "环境变量"
        ctx.console.print("[green]✓ 成功连接本地 Antigravity 凭据！[/green]", highlight=False)
        ctx.console.print(f"  • [bold]凭据来源:[/bold] {source}", highlight=False)
        ctx.console.print(f"  • [bold]项目 ID:[/bold] {creds.project_id}", highlight=False)
        if creds.email:
            ctx.console.print(f"  • [bold]登录账号:[/bold] {creds.email}", highlight=False)

    async def _cmd_model(self, ctx: CommandContext) -> None:
        target_model = ctx.raw_args.strip()
        llm = getattr(getattr(self.agent, "agent", None), "llm", None)
        if not target_model:
            curr_model = "unknown"
            if llm is not None and hasattr(llm, "config") and llm.config is not None:
                curr_model = getattr(llm.config, "model", "unknown")
            ctx.console.print(f"[bold]当前模型:[/bold] [cyan]{curr_model}[/cyan]", highlight=False)
            ctx.console.print("[dim]使用方式: /model <model_name> 切换模型[/dim]", highlight=False)
            ctx.console.print(
                "[dim]常用模型: gemini-3.8-flash, gemini-3.8-pro, gemini-3.7-flash, gpt-4o, claude-3-7-sonnet[/dim]",
                highlight=False,
            )
            return

        if llm is not None:
            if hasattr(llm, "config") and llm.config is not None and hasattr(llm.config, "model_copy"):
                llm.config = llm.config.model_copy(update={"model": target_model})
                if (
                    hasattr(llm, "_provider")
                    and hasattr(llm._provider, "config")
                    and hasattr(llm._provider.config, "model_copy")
                ):
                    llm._provider.config = llm._provider.config.model_copy(update={"model": target_model})
            elif hasattr(llm, "config") and llm.config is not None:
                setattr(llm.config, "model", target_model)
            else:
                llm.config = Config(provider="openai", model=target_model, api_key="placeholder")

        ctx.console.print(f"[green]✓ 模型已成功切换为:[/green] [bold cyan]{target_model}[/bold cyan]", highlight=False)

    async def _cmd_mode(self, ctx: CommandContext) -> None:
        target_mode = ctx.raw_args.strip().lower()
        gate = getattr(self.agent, "permission_gate", None)

        if not target_mode:
            if gate is None:
                ctx.console.print("[yellow]当前会话未启用权限门禁 (PermissionGate)。[/yellow]")
                return
            curr_mode = getattr(gate, "mode", "unknown")
            ctx.console.print(f"[bold]当前权限模式:[/bold] [cyan]{curr_mode}[/cyan]")
            ctx.console.print("[dim]使用方式: /mode [review|yolo|autonomous|strict] 切换安全审查级别[/dim]")
            return

        valid_modes = ("review", "yolo", "autonomous", "strict")
        if target_mode not in valid_modes:
            ctx.console.print(f"[red]无效的权限模式: '{target_mode}'。可选模式: review, yolo, autonomous, strict[/red]")
            return

        if gate is None:
            ctx.console.print("[yellow]当前会话未启用权限门禁 (PermissionGate)，无法切换模式。[/yellow]")
            return

        if target_mode == "yolo":
            gate.mode = "autonomous"
            ctx.console.print("[green]✓ 权限模式已切换为:[/green] [bold cyan]autonomous (yolo)[/bold cyan]")
        else:
            gate.mode = target_mode
            ctx.console.print(f"[green]✓ 权限模式已切换为:[/green] [bold cyan]{target_mode}[/bold cyan]")

    async def _cmd_steer(self, ctx: CommandContext) -> None:
        msg = ctx.raw_args.strip()
        if not msg:
            ctx.console.print("[yellow]用法: /steer <指令内容> (即时干预转向当前执行)[/yellow]")
            return
        self.agent.steer(msg)
        ctx.console.print(f"[green]✓ 已排队即时转向指令:[/green] [cyan]{msg}[/cyan]")

    async def _cmd_followup(self, ctx: CommandContext) -> None:
        msg = ctx.raw_args.strip()
        if not msg:
            ctx.console.print("[yellow]用法: /followup <指令内容> (追加在当前任务完成后自动执行)[/yellow]")
            return
        self.agent.follow_up(msg)
        ctx.console.print(f"[green]✓ 已排队追问指令:[/green] [cyan]{msg}[/cyan]")

    async def _cmd_exit(self, ctx: CommandContext) -> None:
        self.exit_requested = True
        ctx.console.print("[dim]正在退出... 再见！[/dim]")
