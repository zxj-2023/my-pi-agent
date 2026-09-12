"""my-coding-agent 真实模型实操演练与端到端闭环验证脚本。

使用真实 API 凭据（从根目录 .env 读取），在真实临时工作区中驱动智能体：
1. 自动定位代码 (find / grep)
2. 阅读问题函数 (read)
3. 外科手术式修复代码 (edit)
4. 运行 pytest 验证 (bash)
5. 通过 EventRenderer 实时呈现思考链、工具状态指示与 Unified Diff 彩色高亮。
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from rich.console import Console

from my_agent_llm import LLM, Config
from my_coding_agent.agent import CodingAgent
from my_coding_agent.cli_base import _force_utf8_streams
from my_coding_agent.renderer import EventRenderer


def setup_playground(workspace: Path) -> None:
    """初始化一个包含真实缺陷代码和测试套件的演练环境。"""
    src_dir = workspace / "src"
    test_dir = workspace / "tests"
    src_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    # 包含故意引入的减法 Bug
    calc_file = src_dir / "calculator.py"
    calc_file.write_text(
        "def add(a: int, b: int) -> int:\n"
        "    \"\"\"Return the sum of two integers.\"\"\"\n"
        "    return a - b  # BUG: should be a + b\n",
        encoding="utf-8",
    )

    # 验证测试
    test_file = test_dir / "test_calculator.py"
    test_file.write_text(
        "from src.calculator import add\n\n"
        "def test_add():\n"
        "    assert add(10, 25) == 35\n",
        encoding="utf-8",
    )


async def run_demo() -> int:
    _force_utf8_streams()
    load_dotenv(find_dotenv(usecwd=True))

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not configured in .env", file=sys.stderr)
        return 1

    console = Console()
    console.print("[bold cyan]==================================================[/bold cyan]")
    console.print("[bold cyan]  my-coding-agent 真实大模型端到端开发闭环演练  [/bold cyan]")
    console.print("[bold cyan]==================================================[/bold cyan]\n")

    provider = os.environ.get("PI_DEFAULT_PROVIDER", "openai")
    model = os.environ.get("OPENAI_MODEL", "deepseek-flash")
    base_url = os.environ.get("OPENAI_BASE_URL")

    console.print(f"[dim]Provider:[/dim] [green]{provider}[/green]")
    console.print(f"[dim]Model:[/dim]    [green]{model}[/green]")
    console.print(f"[dim]Base URL:[/dim] [green]{base_url}[/green]\n")

    llm = LLM(Config(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.2,
    ))

    with tempfile.TemporaryDirectory(prefix="my-agent-live-demo-") as tmpdir:
        workspace = Path(tmpdir).resolve()
        setup_playground(workspace)
        console.print(f"[bold]临时演练工作区:[/bold] [yellow]{workspace}[/yellow]\n")

        session_path = workspace / ".my_agent_core" / "sessions" / "live_demo.jsonl"
        agent = CodingAgent(workspace=workspace, llm=llm, session=session_path)
        renderer = EventRenderer(console=console)

        instruction = (
            "We have a bug in src/calculator.py where add() returns subtraction instead of addition. "
            "Please read the file, fix it using the edit tool, and run 'pytest' using the bash tool to verify the fix."
        )

        console.print(f"[bold yellow]用户指令:[/bold yellow] {instruction}\n")

        # 流式执行并实时渲染
        async for event in agent.run_stream(instruction):
            renderer.on_event(event)

        # 检查最终修改结果
        fixed_content = (workspace / "src" / "calculator.py").read_text(encoding="utf-8")
        console.print("\n[bold cyan]── 验证演练工作区代码状态 ──[/bold cyan]")
        console.print(f"[bold]src/calculator.py 最终内容:[/bold]\n{fixed_content}")

        if "a + b" in fixed_content:
            console.print("\n[bold green]✓ 演练成功！真实模型准确识别了 Bug，并使用 edit 工具成功修复！[/bold green]\n")
            return 0
        else:
            console.print("\n[bold red]✗ 演练未完全通过：src/calculator.py 未能被修改为 a + b。[/bold red]\n")
            return 1


def main() -> None:
    exit_code = asyncio.run(run_demo())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
