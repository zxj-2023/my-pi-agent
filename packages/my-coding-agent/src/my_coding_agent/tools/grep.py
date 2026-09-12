from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from my_agent_core.tools import Tool, ToolResult, tool

from my_coding_agent.tools.base import (
    DEFAULT_IGNORE_DIRS,
    is_binary_file,
    resolve_path,
)


@dataclass
class GrepResult(ToolResult):
    """Grep 工具执行结果：继承 ToolResult，兼容字符串直接比较与包含操作。"""

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            val = self.data if self.data is not None else self.error
            return str(val) == other
        return super().__eq__(other)

    def __contains__(self, item: Any) -> bool:
        content = self.data if self.data is not None else (self.error or "")
        return str(item) in str(content)

    def __str__(self) -> str:
        return str(self.data if self.data is not None else self.error)

    def __repr__(self) -> str:
        return repr(self.data if self.data is not None else self.error)


def make_grep_tool(workspace: Path | str) -> Tool:
    """创建 grep 工具工厂，在 workspace 内按文本或正则表达式检索文件。"""
    workspace = Path(workspace).resolve()

    @tool(
        name="grep",
        description="Search for regex or literal text patterns across files in the workspace.",
        is_parallel_safe=True,
    )
    async def grep(
        pattern: str,
        path: str = ".",
        regex: bool = False,
        case_sensitive: bool = False,
        max_matches: int = 100,
        glob_filter: str | None = None,
    ) -> str:
        try:
            target_root = resolve_path(workspace, path)
            if not target_root.exists():
                return f"Error: Path not found: {path}"

            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                compiled_regex = re.compile(
                    pattern if regex else re.escape(pattern), flags
                )
            except re.error as e:
                return f"Error: Invalid regular expression: {e}"

            matches: list[str] = []
            files_to_search: list[Path] = []

            if target_root.is_file():
                if not glob_filter or fnmatch.fnmatch(target_root.name, glob_filter):
                    files_to_search = [target_root]
            else:
                for root, dirs, files in os.walk(target_root):
                    dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS]
                    dirs.sort()
                    for f in sorted(files):
                        if glob_filter and not fnmatch.fnmatch(f, glob_filter):
                            continue
                        files_to_search.append(Path(root) / f)

            for file_path in files_to_search:
                if is_binary_file(file_path):
                    continue
                try:
                    rel = file_path.relative_to(workspace)
                except ValueError:
                    rel = file_path

                try:
                    with open(file_path, encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, start=1):
                            if compiled_regex.search(line):
                                clean_line = line.rstrip("\r\n")
                                matches.append(f"{rel}:{lineno}: {clean_line}")
                                if len(matches) >= max_matches:
                                    matches.append(
                                        f"[Reached maximum limit of {max_matches} matches]"
                                    )
                                    return "\n".join(matches)
                except (OSError, UnicodeDecodeError):
                    continue

            return (
                "\n".join(matches)
                if matches
                else f"No matches found for pattern '{pattern}'."
            )
        except Exception as e:
            return f"Error: {e}"

    orig_execute = grep.execute

    async def execute(
        args: dict[str, Any] | None = None,
        signal: Any | None = None,
        on_update: Callable[[Any], None] | None = None,
        tool_call_id: str | None = None,
        **kwargs: Any,
    ) -> GrepResult:
        call_args = dict(args) if isinstance(args, dict) else {}
        call_args.update(kwargs)
        res = await orig_execute(
            call_args,
            signal=signal,
            on_update=on_update,
            tool_call_id=tool_call_id,
        )
        return GrepResult(
            ok=res.ok,
            data=res.data,
            error=res.error,
            meta=res.meta,
            terminate=res.terminate,
        )

    grep.execute = execute
    return grep
