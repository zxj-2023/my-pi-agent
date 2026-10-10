from __future__ import annotations

from pathlib import Path

from my_agent_core.tools import Tool, tool

from my_coding_agent.tools.base import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    PATH_ALIASES,
    StringCompatibleToolResult,
    is_binary_file,
    resolve_path,
    wrap_tool_executor,
)


class ReadResult(StringCompatibleToolResult):
    """Read 工具执行结果：继承 StringCompatibleToolResult。"""


def make_read_tool(workspace: Path) -> Tool:
    workspace = workspace.resolve()

    @tool(
        name="read",
        description="Read file contents with line offset/limit pagination and automatic truncation.",
        prompt_snippet="Read file contents",
        prompt_guidelines=["Use read to examine files instead of cat or sed."],
        is_parallel_safe=True,
    )
    async def read(path: str, offset: int = 1, limit: int | None = None) -> str:
        try:
            target = resolve_path(workspace, path)
            if not target.exists():
                return f"Error: File not found: {path}"
            if target.is_dir():
                return f"Error: Path is a directory: {path}"
            if is_binary_file(target):
                size = target.stat().st_size
                return f"Error: Cannot read binary file ({size} bytes): {path}"

            text = target.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            total_lines = len(lines)

            if offset < 1:
                offset = 1
            if offset > total_lines and total_lines > 0:
                return f"Error: Offset {offset} is beyond end of file ('{path}' has only {total_lines} lines total)."

            start_idx = offset - 1
            effective_limit = limit if limit is not None else DEFAULT_MAX_LINES
            end_idx = min(start_idx + effective_limit, total_lines)

            # 检查 2000 行限制
            is_line_truncated = False
            if end_idx - start_idx > DEFAULT_MAX_LINES:
                end_idx = start_idx + DEFAULT_MAX_LINES
                is_line_truncated = True

            selected_lines = lines[start_idx:end_idx]
            result_text = "\n".join(selected_lines)

            # 检查 50KB 字节限制
            is_byte_truncated = False
            encoded = result_text.encode("utf-8")
            if len(encoded) > DEFAULT_MAX_BYTES:
                encoded = encoded[:DEFAULT_MAX_BYTES]
                last_nl = encoded.rfind(b"\n")
                if last_nl != -1:
                    encoded = encoded[:last_nl]
                result_text = encoded.decode("utf-8", errors="ignore")
                end_idx = start_idx + len(result_text.splitlines())
                is_byte_truncated = True

            truncated = is_line_truncated or is_byte_truncated or (end_idx < total_lines and limit is None)
            if truncated:
                result_text += (
                    f"\n\n[Showing lines {offset}-{end_idx} of {total_lines}. Use offset={end_idx + 1} to continue.]"
                )

            return result_text
        except Exception as e:
            return f"Error: {e}"

    return wrap_tool_executor(read, ReadResult, {"path": PATH_ALIASES})
