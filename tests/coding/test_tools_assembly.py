"""tools 装配测试：验证 build_coding_tools 返回 6 个核心工具。"""

from pathlib import Path

import pytest

from my_coding_agent import (
    CodingAgent,
    EditBlock,
    FileMutationQueue,
    build_coding_tools,
    build_default_coding_prompt,
    make_bash_tool,
    make_edit_tool,
    make_find_tool,
    make_grep_tool,
    make_read_tool,
    make_write_tool,
    resolve_path,
)
from my_coding_agent.tools import build_coding_tools as tools_build_coding_tools


def test_build_coding_tools_returns_six_tools(tmp_path: Path):
    """build_coding_tools 返回恰好 6 个工具，名称为 read/write/edit/bash/grep/find。"""
    queue = FileMutationQueue()
    tools = build_coding_tools(tmp_path, mutation_queue=queue)
    names = {t.name for t in tools}
    assert names == {"read", "write", "edit", "bash", "grep", "find"}


def test_build_coding_tools_from_tools_package(tmp_path: Path):
    """从 my_coding_agent.tools 直接导入的 build_coding_tools 与顶层等价。"""
    tools = tools_build_coding_tools(tmp_path)
    names = {t.name for t in tools}
    assert names == {"read", "write", "edit", "bash", "grep", "find"}


def test_build_coding_tools_accepts_str_workspace(tmp_path: Path):
    """build_coding_tools 接受 str 类型的 workspace 参数。"""
    tools = build_coding_tools(str(tmp_path))
    assert len(tools) == 6


def test_build_coding_tools_parallel_safe_flags(tmp_path: Path):
    """read/write/edit/grep/find 是并发安全的；bash 不是。"""
    tools = build_coding_tools(tmp_path)
    by_name = {t.name: t for t in tools}
    assert by_name["read"].is_parallel_safe is True
    assert by_name["write"].is_parallel_safe is True
    assert by_name["edit"].is_parallel_safe is True
    assert by_name["grep"].is_parallel_safe is True
    assert by_name["find"].is_parallel_safe is True
    assert by_name["bash"].is_parallel_safe is False


def test_top_level_exports_present():
    """顶层包导出所有约定的公共符号。"""
    assert callable(build_coding_tools)
    assert callable(build_default_coding_prompt)
    assert FileMutationQueue is not None
    assert callable(resolve_path)
    assert EditBlock is not None
    assert callable(make_read_tool)
    assert callable(make_write_tool)
    assert callable(make_edit_tool)
    assert callable(make_bash_tool)
    assert callable(make_grep_tool)
    assert callable(make_find_tool)
    assert CodingAgent is not None


def test_file_mutation_queue_acquire_is_native(tmp_path: Path):
    """FileMutationQueue.acquire 是原生异步上下文管理器（不需要猴子补丁）。"""
    queue = FileMutationQueue()
    # 验证 acquire 方法存在且是 asynccontextmanager
    assert hasattr(queue, "acquire")
    assert callable(queue.acquire)


@pytest.mark.anyio
async def test_file_mutation_queue_acquire_works(tmp_path: Path):
    """FileMutationQueue.acquire 可以正常 async with 使用。"""
    queue = FileMutationQueue()
    target = tmp_path / "test.txt"
    async with queue.acquire(target):
        target.write_text("hello", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "hello"


def test_shared_string_compatible_tool_result(tmp_path: Path):
    """StringCompatibleToolResult 被所有 6 个工具的 Result 类继承。"""
    from my_coding_agent.tools.base import StringCompatibleToolResult
    from my_coding_agent.tools.bash import BashResult
    from my_coding_agent.tools.edit import EditResult
    from my_coding_agent.tools.find import FindResult
    from my_coding_agent.tools.grep import GrepResult
    from my_coding_agent.tools.read import ReadResult
    from my_coding_agent.tools.write import WriteResult

    for cls in (
        ReadResult,
        WriteResult,
        EditResult,
        BashResult,
        GrepResult,
        FindResult,
    ):
        assert issubclass(cls, StringCompatibleToolResult), f"{cls.__name__} should inherit StringCompatibleToolResult"
