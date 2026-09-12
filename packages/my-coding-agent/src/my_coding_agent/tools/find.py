from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from my_agent_core.tools import Tool, tool

from my_coding_agent.tools.base import (
    DEFAULT_IGNORE_DIRS,
    StringCompatibleToolResult,
    resolve_path,
)


class FindResult(StringCompatibleToolResult):
    """Find 工具执行结果：继承 StringCompatibleToolResult。"""


def make_find_tool(workspace: Path | str) -> Tool:
    """创建 find 工具工厂，在 workspace 内按 glob pattern 检索文件。"""
    workspace = Path(workspace).resolve()

    @tool(
        name="find",
        description="Find files matching a glob pattern, automatically filtering out cache and virtualenv directories.",
        is_parallel_safe=True,
    )
    async def find(pattern: str = "*", path: str = ".", limit: int = 100) -> str:
        try:
            target_root = resolve_path(workspace, path)
            if not target_root.exists():
                return f"Error: Path not found: {path}"

            matched_paths: list[str] = []
            norm_pattern = pattern.replace("\\", "/")

            if target_root.is_file():
                try:
                    rel = str(target_root.relative_to(workspace)).replace("\\", "/")
                except ValueError:
                    rel = str(target_root).replace("\\", "/")
                if (
                    fnmatch.fnmatch(rel, norm_pattern)
                    or fnmatch.fnmatch(rel, pattern)
                    or fnmatch.fnmatch(target_root.name, pattern)
                ):
                    matched_paths.append(rel)
                    if len(matched_paths) >= limit:
                        matched_paths.append(f"[Truncated at limit of {limit} results]")
                        return "\n".join(matched_paths)
            else:
                for root, dirs, files in os.walk(target_root):
                    dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS]
                    dirs.sort()
                    for f in sorted(files):
                        full_p = Path(root) / f
                        try:
                            rel = str(full_p.relative_to(workspace)).replace("\\", "/")
                        except ValueError:
                            rel = str(full_p).replace("\\", "/")

                        if (
                            fnmatch.fnmatch(rel, norm_pattern)
                            or fnmatch.fnmatch(rel, pattern)
                            or fnmatch.fnmatch(f, pattern)
                        ):
                            matched_paths.append(rel)
                            if len(matched_paths) >= limit:
                                matched_paths.append(
                                    f"[Truncated at limit of {limit} results]"
                                )
                                return "\n".join(matched_paths)

            return (
                "\n".join(matched_paths)
                if matched_paths
                else f"No files matching '{pattern}' found."
            )
        except Exception as e:
            return f"Error: {e}"

    orig_execute = find.execute

    async def execute(
        args: dict[str, Any] | None = None,
        signal: Any | None = None,
        on_update: Callable[[Any], None] | None = None,
        tool_call_id: str | None = None,
        **kwargs: Any,
    ) -> FindResult:
        call_args = dict(args) if isinstance(args, dict) else {}
        call_args.update(kwargs)
        res = await orig_execute(
            call_args,
            signal=signal,
            on_update=on_update,
            tool_call_id=tool_call_id,
        )
        return FindResult(
            ok=res.ok,
            data=res.data,
            error=res.error,
            meta=res.meta,
            terminate=res.terminate,
        )

    find.execute = execute
    return find
