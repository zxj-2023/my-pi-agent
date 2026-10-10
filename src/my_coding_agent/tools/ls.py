from __future__ import annotations

import contextlib
import os
from pathlib import Path

from my_agent_core.tools import Tool, tool

from my_coding_agent.tools.base import (
    DEFAULT_MAX_BYTES,
    PATH_ALIASES,
    resolve_path,
    wrap_tool_executor,
)

DEFAULT_LS_LIMIT = 500


def make_ls_tool(workspace: Path | str) -> Tool:
    """创建工作区绑定的 ls 工具（对标 Pi 官方 ls 实现）。

    - path: 目录路径（默认当前工作目录 "."）
    - limit: 最多返回条目数（默认 500）
    - 排序：按字母不区分大小写排序，目录带 '/' 后缀
    - 包含点文件（dotfiles），输出截断至 500 条或 50KB
    """
    workspace = Path(workspace).resolve()

    @tool(
        name="ls",
        description="List directory contents. Returns entries sorted alphabetically, with '/' suffix for directories. Includes dotfiles. Output is truncated to 500 entries or 50KB (whichever is hit first).",
        prompt_snippet="List directory contents",
        is_parallel_safe=True,
    )
    async def ls(path: str = ".", limit: int = DEFAULT_LS_LIMIT) -> str:
        try:
            target = resolve_path(workspace, path)
            if not target.exists():
                return f"Error: Path not found: {path}"
            if not target.is_dir():
                return f"Error: Not a directory: {path}"

            try:
                raw_entries = os.listdir(target)
            except OSError as e:
                return f"Error: Cannot read directory: {e}"

            # 字母不区分大小写排序
            raw_entries.sort(key=lambda s: s.lower())

            effective_limit = limit if (limit is not None and limit > 0) else DEFAULT_LS_LIMIT
            results: list[str] = []
            truncated_by_limit = False

            for entry in raw_entries:
                if len(results) >= effective_limit:
                    truncated_by_limit = True
                    break
                full_path = target / entry
                suffix = ""
                with contextlib.suppress(OSError):
                    if full_path.is_dir():
                        suffix = "/"
                results.append(f"{entry}{suffix}")

            output = "\n".join(results)
            encoded = output.encode("utf-8")
            if len(encoded) > DEFAULT_MAX_BYTES:
                encoded = encoded[:DEFAULT_MAX_BYTES]
                last_nl = encoded.rfind(b"\n")
                if last_nl != -1:
                    encoded = encoded[:last_nl]
                output = encoded.decode("utf-8", errors="ignore")
                output += f"\n\n[Output truncated: output exceeded {DEFAULT_MAX_BYTES // 1024}KB limit]"
            elif truncated_by_limit:
                output += f"\n\n[Output truncated: reached entry limit of {effective_limit}]"

            return output if output else "(Empty directory)"
        except Exception as e:
            return f"Error: {e}"

    return wrap_tool_executor(
        ls,
        aliases={"path": ("directory", "dir", "folder", *PATH_ALIASES)},
    )
