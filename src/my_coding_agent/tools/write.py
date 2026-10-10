from __future__ import annotations

from pathlib import Path

from my_agent_core.tools import Tool, tool

from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.tools.base import (
    PATH_ALIASES,
    resolve_path,
    wrap_tool_executor,
)


def make_write_tool(workspace: Path, mutation_queue: FileMutationQueue | None = None) -> Tool:
    """创建工作区绑定的 write 工具。

    - workspace: 工作区根目录路径
    - mutation_queue: 单文件并发互斥锁队列，缺省时自动新建
    """
    workspace = Path(workspace).resolve()
    queue = mutation_queue or FileMutationQueue()

    @tool(
        name="write",
        description="Write complete content to a file, automatically creating parent directories.",
        prompt_snippet="Create or overwrite files",
        prompt_guidelines=["Use write only for new files or complete rewrites."],
        is_parallel_safe=True,
    )
    async def write(path: str, content: str) -> str:
        try:
            target = resolve_path(workspace, path)
            if target.is_dir():
                return f"Error: Path is a directory: {path}"

            async with queue.acquire(target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="")
                bytes_count = len(content.encode("utf-8"))
                lines_count = len(content.splitlines())
                return f"Successfully wrote {bytes_count} bytes ({lines_count} lines) to {path}"
        except Exception as e:
            return f"Error: {e}"

    return wrap_tool_executor(
        write,
        aliases={"path": PATH_ALIASES, "content": ("contents", "text")},
    )
