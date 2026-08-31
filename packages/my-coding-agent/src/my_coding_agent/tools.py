"""文件工具：四个工厂（read/edit/write/bash）+ 路径逃逸防护 + FileMutationQueue 细粒度并发写锁。"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from subprocess import PIPE, Popen
from typing import TYPE_CHECKING

from my_agent_core.tools import Tool  # pyright: ignore[reportMissingImports]

if TYPE_CHECKING:
    from my_agent_core.background import (  # pyright: ignore[reportMissingImports]
        BackgroundRunner,
    )

from my_coding_agent.mutation_queue import FileMutationQueue

_TIMEOUT_SECONDS = 120
_DANGEROUS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]


def _safe_path(root: Path, p: str) -> Path:
    """把 p（相对或绝对）解析到 root 内，逃逸 → ValueError。"""
    path = (root / p).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def make_read_tool(root: str | Path) -> Tool:
    """read(path, limit=None, offset=None)：精细化读文件（附带行号统计与越界提示）。"""
    root = Path(root).resolve()

    def read(path: str, limit: int | None = None, offset: int | None = None) -> str:
        """Read file contents with line limits and offset. Use for large files."""
        try:
            fp = _safe_path(root, path)
            if not fp.exists():
                return f"Error: File '{path}' does not exist."
            if fp.is_dir():
                return f"Error: '{path}' is a directory, not a regular file."

            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(lines)

            start_idx = 0
            if offset is not None:
                if offset > total_lines:
                    return f"Error: Offset {offset} is beyond end of file ('{path}' has only {total_lines} lines total)."
                start_idx = max(0, offset - 1)

            selected_lines = lines[start_idx:]
            if limit is not None and limit < len(selected_lines):
                remaining = len(selected_lines) - limit
                selected_lines = selected_lines[:limit] + [
                    f"... ({remaining} more lines, {total_lines} lines total)"
                ]

            return "\n".join(selected_lines)[:50000]
        except Exception as e:
            return f"Error: {e}"

    return Tool(func=read, name="read", is_parallel_safe=True)


def make_write_tool(
    root: str | Path, mutation_queue: FileMutationQueue | None = None
) -> Tool:
    """write(path, content)：覆盖写（单文件互斥锁保护，天然并发安全）。"""
    root = Path(root).resolve()
    queue = mutation_queue or FileMutationQueue()

    async def write(path: str, content: str) -> str:
        """Write content to file. Creates/overwrites the file safely."""
        try:
            fp = _safe_path(root, path)
            lock = await queue.get_lock(fp)
            async with lock:
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content, encoding="utf-8")
                line_count = len(content.splitlines())
                return f"Wrote {len(content)} bytes ({line_count} lines) to {path}"
        except Exception as e:
            return f"Error writing to '{path}': {e}"

    return Tool(func=write, name="write", is_parallel_safe=True)


def make_edit_tool(
    root: str | Path, mutation_queue: FileMutationQueue | None = None
) -> Tool:
    """edit(path, old_text, new_text)：精确替换一次（单文件互斥锁保护 + 多重匹配与未找到精准提示）。"""
    root = Path(root).resolve()
    queue = mutation_queue or FileMutationQueue()

    async def edit(path: str, old_text: str, new_text: str) -> str:
        """Replace exact text in file (first unique occurrence only)."""
        try:
            fp = _safe_path(root, path)
            if not fp.exists():
                return f"Error: File '{path}' does not exist."
            if fp.is_dir():
                return f"Error: '{path}' is a directory, not a regular file."

            lock = await queue.get_lock(fp)
            async with lock:
                content = fp.read_text(encoding="utf-8", errors="replace")
                match_count = content.count(old_text)
                total_lines = len(content.splitlines())

                if match_count == 0:
                    return (
                        f"Error: Text not found in {path} (file has {total_lines} lines total). "
                        f"Tip: Check exact whitespace, indentation, and newlines, or call read('{path}') first."
                    )

                if match_count > 1:
                    return (
                        f"Error: Could not edit '{path}': old_text matched {match_count} locations. "
                        f"Please provide more surrounding context lines to ensure a unique match."
                    )

                new_content = content.replace(old_text, new_text, 1)
                fp.write_text(new_content, encoding="utf-8")
                return f"Edited {path} successfully (1 replacement made)"
        except Exception as e:
            return f"Error editing '{path}': {e}"

    return Tool(func=edit, name="edit", is_parallel_safe=True)


def _format_timeout_output(command: str, partial_out: str | None, partial_err: str | None) -> str:
    parts: list[str] = []
    if partial_out:
        parts.append(partial_out)
    if partial_err:
        parts.append(partial_err)
    captured = "".join(parts).strip()
    partial_text = captured[-2000:] if captured else "(no output captured before timeout)"
    return (
        f"Error: Timeout ({_TIMEOUT_SECONDS}s) for command '{command}'.\n"
        f"=== Output before timeout ===\n"
        f"{partial_text}\n"
        f"=== End of output ===\n"
        f"Tip: The command may be waiting for interactive stdin. Pass non-interactive flags (e.g. -y) or check for long-running loops."
    )


def make_bash_tool(
    root: str | Path, background_runner: BackgroundRunner | None = None
) -> Tool:
    """bash(command, run_in_background=False)：在 root 下执行 shell，支持后台异步执行。"""
    root = Path(root).resolve()

    async def bash(command: str, run_in_background: bool = False) -> str:
        """Run a shell command in the workspace root."""
        if any(d in command for d in _DANGEROUS):
            return "Error: Dangerous command blocked"

        if run_in_background:
            if background_runner is None:
                return "Error: Background runner is not configured"
            job_id = await background_runner.run_process(command, cwd=root)
            return f"[Background task {job_id} started for command: '{command}']"

        try:
            cmd_args = (
                ["cmd.exe", "/c", command]
                if os.name == "nt"
                else ["/bin/sh", "-c", command]
            )

            def _sync_run() -> str:
                proc = Popen(
                    cmd_args,
                    cwd=root,
                    stdout=PIPE,
                    stderr=PIPE,
                    text=True,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=_TIMEOUT_SECONDS)
                    out = (stdout + stderr).strip()
                    return out[:50000] if out else "(no output)"
                except subprocess.TimeoutExpired:
                    proc.kill()
                    partial_out, partial_err = proc.communicate()
                    return _format_timeout_output(command, partial_out, partial_err)

            return await asyncio.to_thread(_sync_run)
        except OSError as e:
            return f"Error: {e}"

    return Tool(func=bash, name="bash", is_parallel_safe=False)
