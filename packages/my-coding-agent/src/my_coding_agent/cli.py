import argparse
import asyncio
import os
from pathlib import Path
from typing import Sequence

from dotenv import find_dotenv, load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from rich.console import Console

from my_agent_llm import LLM, Config
from my_coding_agent.agent import CodingAgent
from my_coding_agent.cli_base import _force_utf8_streams
from my_coding_agent.commands import CommandDispatcher
from my_coding_agent.renderer import EventRenderer

SLASH_COMMANDS = ["/help", "/clear", "/undo", "/compact", "/session", "/tasks", "/mcp", "/exit", "/quit"]


def build_prompt_session(workspace: Path) -> PromptSession:
    """构建带历史文件和斜杠命令自动补全的 prompt_toolkit 会话。"""
    hist_dir = workspace / ".my_agent_core"
    hist_dir.mkdir(parents=True, exist_ok=True)
    hist_file = str(hist_dir / "cli_history")
    completer = WordCompleter(SLASH_COMMANDS, ignore_case=True, sentence=True)
    try:
        return PromptSession(history=FileHistory(hist_file), completer=completer)
    except Exception:
        from prompt_toolkit.output import DummyOutput

        return PromptSession(history=FileHistory(hist_file), completer=completer, output=DummyOutput())


async def run_cli_loop(
    agent: CodingAgent,
    console: Console,
    prompt_session: PromptSession | None = None,
    dispatcher: CommandDispatcher | None = None,
) -> None:
    """交互式 REPL 循环：接收输入、分发斜杠命令、驱动流式事件渲染。"""
    session = prompt_session if prompt_session is not None else build_prompt_session(agent.workspace)
    cmd_dispatcher = dispatcher if dispatcher is not None else CommandDispatcher(agent)
    renderer = EventRenderer(console)

    console.print(f"[bold green]my-coding-agent 终端编程助手[/bold green] [dim](工作区: {agent.workspace})[/dim]")
    console.print("[dim]输入提问，输入 [bold]/help[/bold] 查看命令，按 [bold]Ctrl+D[/bold] 退出。[/dim]\n")

    while not cmd_dispatcher.exit_requested:
        try:
            user_input = await session.prompt_async(">>> ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见！[/dim]")
            break

        cleaned = user_input.strip()
        if not cleaned:
            continue

        if await cmd_dispatcher.dispatch(cleaned, console):
            if cmd_dispatcher.exit_requested:
                break
            continue

        try:
            async for event in agent.run_stream(cleaned):
                renderer.on_event(event)
        except (asyncio.CancelledError, KeyboardInterrupt):
            console.print("\n[yellow]已取消当前生成轮次。[/yellow]")
        except Exception as e:
            console.print(f"\n[red]运行出错: {e}[/red]")


def main(argv: Sequence[str] | None = None, llm: LLM | None = None) -> None:
    """CLI 主入口函数，支持 -w/--workspace 与 -m/--model 参数。"""
    _force_utf8_streams()
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(description="my-coding-agent 交互式编码助手")
    parser.add_argument("-w", "--workspace", default=".", help="工作区路径")
    parser.add_argument("-m", "--model", default=None, help="LLM 模型标识符")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    console = Console()

    # 初始化默认 LLM（若未外部注入）
    if llm is None:
        provider_name = os.environ.get("PI_DEFAULT_PROVIDER", "openai")
        model_name = (
            args.model
            or os.environ.get(f"{provider_name.upper()}_MODEL")
            or os.environ.get("PI_DEFAULT_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or "gpt-4o"
        )
        api_key = (
            os.environ.get(f"{provider_name.upper()}_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("PI_API_KEY")
            or "placeholder"
        )
        base_url = os.environ.get(f"{provider_name.upper()}_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        llm = LLM(Config(provider=provider_name, model=model_name, api_key=api_key, base_url=base_url))

    session_path = workspace / ".my_agent_core" / "sessions" / "default_session.jsonl"
    agent = CodingAgent(workspace=workspace, llm=llm, session=session_path)

    asyncio.run(run_cli_loop(agent, console))


if __name__ == "__main__":
    main()
