from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from my_agent_core.tools import Tool, tool

from my_coding_agent.tools.base import (
    DEFAULT_IGNORE_DIRS,
    PATH_ALIASES,
    is_binary_file,
    resolve_path,
    truncate_output,
    wrap_tool_executor,
)


def make_grep_tool(workspace: Path | str) -> Tool:
    """创建 grep 工具工厂，在 workspace 内检索文件（对标 Pi 官方 grep 协议与参数）。"""
    workspace = Path(workspace).resolve()

    @tool(
        name="grep",
        description="Search file contents for patterns (respects .gitignore). Supports regex, case sensitivity, context lines, glob filter, and line limits.",
        prompt_snippet="Search file contents for patterns (respects .gitignore)",
        is_parallel_safe=True,
    )
    async def grep(
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        ignore_case: bool | None = None,
        literal: bool | None = None,
        context: int = 0,
        limit: int | None = None,
        regex: bool = False,
        case_sensitive: bool = False,
    ) -> str:
        try:
            target_root = resolve_path(workspace, path)
            if not target_root.exists():
                return f"Error: Path not found: {path}"

            # 解析大小写敏感度（Pi 规范优先: ignoreCase / ignore_case）
            actual_ignore_case = True
            if ignore_case is not None:
                actual_ignore_case = bool(ignore_case)
            elif case_sensitive:
                actual_ignore_case = False

            # 解析字面量检索（Pi 规范: literal=True 优先，否则 regex=True）
            is_literal = False
            if literal is not None:
                is_literal = bool(literal)
            else:
                is_literal = not regex

            flags = re.IGNORECASE if actual_ignore_case else 0
            try:
                regex_pat = re.escape(pattern) if is_literal else pattern
                compiled_regex = re.compile(regex_pat, flags)
            except re.error as e:
                return f"Error: Invalid regular expression: {e}"

            effective_glob = glob
            effective_limit = limit if limit is not None else 100
            effective_context = max(0, context)

            matches: list[str] = []
            files_to_search: list[Path] = []

            if target_root.is_file():
                if not effective_glob or fnmatch.fnmatch(target_root.name, effective_glob):
                    files_to_search = [target_root]
            else:
                for root, dirs, files in os.walk(target_root):
                    dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS]
                    dirs.sort()
                    for f in sorted(files):
                        if effective_glob and not fnmatch.fnmatch(f, effective_glob):
                            continue
                        files_to_search.append(Path(root) / f)

            for file_path in files_to_search:
                if is_binary_file(file_path):
                    continue
                try:
                    rel_str = str(file_path.relative_to(workspace)).replace("\\", "/")
                except ValueError:
                    rel_str = str(file_path).replace("\\", "/")

                try:
                    with open(file_path, encoding="utf-8", errors="replace") as f:
                        file_lines = f.read().splitlines()

                    matched_line_indices = [idx for idx, line in enumerate(file_lines) if compiled_regex.search(line)]

                    if not matched_line_indices:
                        continue

                    # 处理上下文行合并
                    if effective_context > 0:
                        emitted_indices: set[int] = set()
                        for idx in matched_line_indices:
                            start_ctx = max(0, idx - effective_context)
                            end_ctx = min(len(file_lines), idx + effective_context + 1)
                            for c_idx in range(start_ctx, end_ctx):
                                if c_idx not in emitted_indices:
                                    emitted_indices.add(c_idx)
                                    sep = ":" if c_idx == idx else "-"
                                    matches.append(f"{rel_str}{sep}{c_idx + 1}: {file_lines[c_idx]}")
                                    if len(matches) >= effective_limit:
                                        matches.append(f"[Reached maximum limit of {effective_limit} matches]")
                                        return "\n".join(matches)
                    else:
                        for idx in matched_line_indices:
                            matches.append(f"{rel_str}:{idx + 1}: {file_lines[idx]}")
                            if len(matches) >= effective_limit:
                                matches.append(f"[Reached maximum limit of {effective_limit} matches]")
                                return "\n".join(matches)

                except (OSError, UnicodeDecodeError):
                    continue

            output = "\n".join(matches) if matches else f"No matches found for pattern '{pattern}'."
            return truncate_output(output)
        except Exception as e:
            return f"Error: {e}"

    return wrap_tool_executor(
        grep,
        aliases={
            "pattern": ("query", "search"),
            "path": ("directory", "dir", "folder", *PATH_ALIASES),
            "ignore_case": ("ignoreCase",),
            "glob": ("glob_filter",),
            "limit": ("max_matches",),
        },
    )
