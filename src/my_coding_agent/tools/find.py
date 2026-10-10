from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from my_agent_core.tools import Tool, tool

from my_coding_agent.tools.base import (
    DEFAULT_IGNORE_DIRS,
    PATH_ALIASES,
    resolve_path,
    truncate_output,
    wrap_tool_executor,
)

DEFAULT_FIND_LIMIT = 1000


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
            return truncate_output(output)
        except Exception as e:
            return f"Error: {e}"

    return wrap_tool_executor(
        find,
        aliases={
            "pattern": ("query", "glob"),
            "path": ("directory", "dir", "folder", *PATH_ALIASES),
        },
    )
