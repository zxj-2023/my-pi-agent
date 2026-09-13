from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

# 使用 ASCII 安全的 Unicode 转义字符，避免 Windows/平台环境编码损坏
ICON_DIR = "\U0001f4c1"  # 📁
ICON_GIT = "\U0001f33f"  # 🌿
ICON_MODEL = "\U0001f916"  # 🤖
ICON_TOKENS = "\U0001f4ca"  # 📊
ICON_TIME = "\u23f1\ufe0f"  # ⏱️


def resolve_git_branch(cwd: Path) -> str | None:
    """轻量调用 git symbolic-ref 获取当前分支名，非 git 仓库或游离 HEAD 优雅返回 None。"""
    try:
        res = subprocess.run(
            ["git", "--no-optional-locks", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        return None
    return None


def format_cwd_for_footer(cwd: Path, home: Path | None = None) -> str:
    """自动将用户主目录路径缩写为 ~/ 开头，跨平台规范化路径分隔符。"""
    resolved_cwd = cwd.resolve()
    resolved_home = (home or Path.home()).resolve()
    try:
        rel = resolved_cwd.relative_to(resolved_home)
        if str(rel) == ".":
            return "~"
        return f"~/{rel}".replace("\\", "/")
    except ValueError:
        return str(resolved_cwd).replace("\\", "/")


def format_tokens(count: int) -> str:
    """紧凑格式化 Token 计数（如 500, 14.2k, 1.0M）。"""
    try:
        num = int(count)
    except (TypeError, ValueError):
        return "0"

    if num < 1000:
        return str(num)
    if num < 1_000_000:
        return f"{num / 1000:.1f}k"
    return f"{num / 1_000_000:.1f}M"


class FooterComponent:
    """对标 Pi footer.ts 的终端状态底栏仪表盘。"""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def render(self, agent: Any, elapsed: float | None = None) -> None:
        workspace = getattr(agent, "workspace", Path.cwd())
        if isinstance(workspace, str):
            workspace = Path(workspace)
        cwd_str = format_cwd_for_footer(workspace)
        branch = resolve_git_branch(workspace)
        branch_str = f"{ICON_GIT} {branch}" if branch else f"{ICON_GIT} (no git)"

        # 提取模型与思考级别
        llm = getattr(getattr(agent, "agent", None), "llm", None) or getattr(agent, "llm", None)
        model_name = getattr(getattr(llm, "config", None), "model", None) or getattr(llm, "model", None)
        if callable(model_name):
            model_name = model_name()
        if not model_name and llm is not None:
            name = type(llm).__name__.lower()
            if "fake" in name:
                model_name = "fake"
            else:
                model_name = "default"
        if not model_name:
            model_name = "default"

        # 统计当前会话 Token
        tokens_used = 0
        session = getattr(agent, "session", None) or getattr(getattr(agent, "agent", None), "session", None)
        if session and hasattr(session, "tree"):
            path = session.tree.get_current_path()
            for entry in path:
                meta = getattr(entry, "metadata", None)
                if isinstance(meta, dict):
                    usage = meta.get("usage")
                    if isinstance(usage, dict):
                        try:
                            tokens_used += int(usage.get("total_tokens", 0) or 0)
                        except (TypeError, ValueError):
                            pass
                    elif usage is not None and hasattr(usage, "total_tokens"):
                        try:
                            tokens_used += int(getattr(usage, "total_tokens", 0) or 0)
                        except (TypeError, ValueError):
                            pass
            if tokens_used == 0 and path:
                tokens_used = len(path) * 150

        tokens_str = format_tokens(tokens_used)

        line = Text()
        line.append(f"{ICON_DIR} {cwd_str} ", style="bold cyan")
        line.append(f"[{branch_str}] ", style="green")
        line.append(f"[{ICON_MODEL} {model_name}] ", style="magenta")
        line.append(f"[{ICON_TOKENS} Tokens: {tokens_str}] ", style="yellow")
        if elapsed is not None and elapsed > 0:
            line.append(f"[{ICON_TIME} {elapsed:.1f}s] ", style="dim")

        self.console.print(line)
