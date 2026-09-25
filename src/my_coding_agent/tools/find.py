from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from my_agent_core.tools import Tool, tool

from my_coding_agent.tools.base import (
    DEFAULT_IGNORE_DIRS,
    DEFAULT_MAX_BYTES,
    StringCompatibleToolResult,
    resolve_path,
)

DEFAULT_FIND_LIMIT = 1000


class FindResult(StringCompatibleToolResult):
    """Find 工具执行结果：继承 StringCompatibleToolResult。"""


def make_find_tool(workspace: Path | str) -> Tool:
    """创建 find 工具工厂，在 workspace 内按 glob pattern 检索文件。"""
    workspace = Path(workspace).resolve()

    @tool(
        name="find",
        description="Search for files by glob pattern. Returns matching file paths relative to the search directory. Output is truncated to 1000 results or 50KB (whichever is hit first).",
        prompt_snippet="Find files by glob pattern (respects .gitignore)",
        is_parallel_safe=True,
    )
    async def find(pattern: str = "*", path: str = ".", limit: int = DEFAULT_FIND_LIMIT) -> str:
        try:
            target_root = resolve_path(workspace, path)
            if not target_root.exists():
                return f"Error: Path not found: {path}"

            effective_limit = limit if (limit is not None and limit > 0) else DEFAULT_FIND_LIMIT
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
                            if len(matched_paths) >= effective_limit:
                                matched_paths.append(f"[Truncated at limit of {effective_limit} results]")
                                break
                    if len(matched_paths) >= effective_limit:
                        break

            output = "\n".join(matched_paths) if matched_paths else f"No files matching '{pattern}' found."
            encoded = output.encode("utf-8")
            if len(encoded) > DEFAULT_MAX_BYTES:
                encoded = encoded[:DEFAULT_MAX_BYTES]
                last_nl = encoded.rfind(b"\n")
                if last_nl != -1:
                    encoded = encoded[:last_nl]
                output = encoded.decode("utf-8", errors="ignore")
                output += f"\n\n[Output truncated: exceeded {DEFAULT_MAX_BYTES // 1024}KB limit]"

            return output
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
