from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from my_agent_core.tools import Tool, tool

from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.tools.base import StringCompatibleToolResult, resolve_path


class WriteResult(StringCompatibleToolResult):
    """Write 工具执行结果：继承 StringCompatibleToolResult。"""


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

    orig_execute = write.execute

    async def execute(
        args: dict[str, Any] | None = None,
        signal: Any | None = None,
        on_update: Callable[[Any], None] | None = None,
        tool_call_id: str | None = None,
        **kwargs: Any,
    ) -> WriteResult:
        call_args = dict(args) if isinstance(args, dict) else {}
        call_args.update(kwargs)
        res = await orig_execute(
            call_args,
            signal=signal,
            on_update=on_update,
            tool_call_id=tool_call_id,
        )
        return WriteResult(
            ok=res.ok,
            data=res.data,
            error=res.error,
            meta=res.meta,
            terminate=res.terminate,
        )

    write.execute = execute
    return write
