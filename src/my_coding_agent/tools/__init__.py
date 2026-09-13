"""文件工具包：6 个核心工具工厂 + build_coding_tools 装配入口。"""

from pathlib import Path
from typing import TYPE_CHECKING

from my_agent_core.tools import Tool  # pyright: ignore[reportMissingImports]

if TYPE_CHECKING:
    from my_agent_core.background import (  # pyright: ignore[reportMissingImports]
        BackgroundRunner,
    )

from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.tools.base import is_binary_file, resolve_path
from my_coding_agent.tools.bash import make_bash_tool
from my_coding_agent.tools.edit import EditBlock, make_edit_tool
from my_coding_agent.tools.find import make_find_tool
from my_coding_agent.tools.grep import make_grep_tool
from my_coding_agent.tools.read import make_read_tool
from my_coding_agent.tools.write import make_write_tool


def build_coding_tools(
    workspace: str | Path,
    mutation_queue: FileMutationQueue | None = None,
    background_runner: "BackgroundRunner | None" = None,
) -> list[Tool]:
    """返回 6 个核心文件工具（read/write/edit/bash/grep/find），各绑定 workspace。"""
    workspace_path = Path(workspace).resolve()
    queue = mutation_queue or FileMutationQueue()
    return [
        make_read_tool(workspace_path),
        make_write_tool(workspace_path, mutation_queue=queue),
        make_edit_tool(workspace_path, mutation_queue=queue),
        make_bash_tool(workspace_path, background_runner=background_runner),
        make_grep_tool(workspace_path),
        make_find_tool(workspace_path),
    ]


__all__ = [
    "build_coding_tools",
    "resolve_path",
    "is_binary_file",
    "make_read_tool",
    "make_write_tool",
    "make_edit_tool",
    "EditBlock",
    "make_bash_tool",
    "make_grep_tool",
    "make_find_tool",
]
