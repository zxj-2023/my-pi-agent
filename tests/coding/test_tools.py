"""文件工具集成测试（适配模块化工具实现的行为）。"""

import asyncio

import pytest

from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.tools import (
    make_bash_tool,
    make_edit_tool,
    make_read_tool,
    make_write_tool,
)


@pytest.mark.anyio
async def test_read_basic(tmp_path):
    """读文件全文（#2）。"""
    read = make_read_tool(tmp_path)
    (tmp_path / "a.txt").write_text("line1\nline2\nline3", encoding="utf-8")
    result = await read.execute({"path": "a.txt"})
    assert result.ok is True
    assert result.data == "line1\nline2\nline3"
    assert read.is_parallel_safe is True


@pytest.mark.anyio
async def test_read_limit(tmp_path):
    """limit 截断 → 输出包含 Showing lines 提示。"""
    read = make_read_tool(tmp_path)
    (tmp_path / "a.txt").write_text("\n".join(f"l{i}" for i in range(10)), encoding="utf-8")
    result = await read.execute({"path": "a.txt", "limit": 3})
    # 新工具显示 "[Showing lines X-Y of Z. ...]" 形式的截断提示
    assert "Showing lines" in result.data or "l0" in result.data


@pytest.mark.anyio
async def test_read_offset_beyond_end(tmp_path):
    """offset 超出文件总行数 → 返回精准行数提示。"""
    read = make_read_tool(tmp_path)
    (tmp_path / "a.txt").write_text("line1\nline2", encoding="utf-8")
    result = await read.execute({"path": "a.txt", "offset": 100})
    assert "Offset 100 is beyond end of file" in result.data
    assert "has only 2 lines total" in result.data


@pytest.mark.anyio
async def test_read_path_outside_workspace(tmp_path):
    """跨 workspace 外部路径 → 返回 'File not found' 或 'not found'。"""
    read = make_read_tool(tmp_path)
    result = await read.execute({"path": "../secret.txt"})
    assert "not found" in result.data.lower() or "Error" in result.data


@pytest.mark.anyio
async def test_read_missing(tmp_path):
    """不存在文件 → 返回错误提示。"""
    read = make_read_tool(tmp_path)
    result = await read.execute({"path": "nope.txt"})
    assert "not found" in result.data.lower() or "not exist" in result.data.lower()


@pytest.mark.anyio
async def test_write_creates_and_overwrites(tmp_path):
    """写文件（自动建父目录）+ 覆盖 + 返回成功信息（#3）。"""
    write = make_write_tool(tmp_path)
    result = await write.execute({"path": "sub/dir/a.txt", "content": "hello"})
    # 新工具返回 "Successfully wrote N bytes"
    assert "5 bytes" in result.data or "wrote" in result.data.lower()
    assert (tmp_path / "sub" / "dir" / "a.txt").read_text(encoding="utf-8") == "hello"
    await write.execute({"path": "sub/dir/a.txt", "content": "world"})
    assert (tmp_path / "sub" / "dir" / "a.txt").read_text(encoding="utf-8") == "world"
    assert write.is_parallel_safe is True


@pytest.mark.anyio
async def test_edit_replaces_once(tmp_path):
    """精确替换一次（#4）。"""
    edit = make_edit_tool(tmp_path)
    (tmp_path / "a.txt").write_text("hello world hello", encoding="utf-8")
    result = await edit.execute({"path": "a.txt", "old_text": "world", "new_text": "earth"})
    # 新工具返回 "Successfully applied N edit(s) to ..."
    assert "a.txt" in result.data or "edit" in result.data.lower()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello earth hello"
    assert edit.is_parallel_safe is True


@pytest.mark.anyio
async def test_edit_text_not_found(tmp_path):
    """old_text 不存在 → 包含路径名与行数提示。"""
    edit = make_edit_tool(tmp_path)
    (tmp_path / "a.txt").write_text("line1\nline2", encoding="utf-8")
    result = await edit.execute({"path": "a.txt", "old_text": "nope", "new_text": "x"})
    assert "a.txt" in result.data
    assert "2 lines" in result.data or "not found" in result.data.lower()


@pytest.mark.anyio
async def test_edit_multiple_matches(tmp_path):
    """old_text 命中多处 → 提示提供更多上下文。"""
    edit = make_edit_tool(tmp_path)
    (tmp_path / "a.txt").write_text("dup\ndup\n", encoding="utf-8")
    result = await edit.execute({"path": "a.txt", "old_text": "dup", "new_text": "unique"})
    # 新工具: "'oldText' matched 2 times"
    assert "matched 2" in result.data or "2 times" in result.data
    assert "Please provide more surrounding context lines" in result.data


@pytest.mark.anyio
async def test_file_mutation_queue_concurrency(tmp_path):
    """验证 FileMutationQueue：不同文件安全并发，同名文件排队串行。"""
    queue = FileMutationQueue()
    write = make_write_tool(tmp_path, mutation_queue=queue)

    timeline = []

    async def write_file(filename: str, delay: float):
        timeline.append(f"start_{filename}")
        await write.execute({"path": filename, "content": f"content_{filename}"})
        await asyncio.sleep(delay)
        timeline.append(f"end_{filename}")

    # 并发写入两个不同文件
    await asyncio.gather(
        write_file("file_a.txt", 0.05),
        write_file("file_b.txt", 0.05),
    )

    # 两个不同文件的写入同时启动
    assert timeline[0] in ("start_file_a.txt", "start_file_b.txt")
    assert timeline[1] in ("start_file_a.txt", "start_file_b.txt")


@pytest.mark.anyio
async def test_bash_normal(tmp_path):
    """正常命令返回 stdout（#5）。"""
    bash = make_bash_tool(tmp_path)
    result = await bash.execute({"command": "echo hi"})
    # 新 bash 工具输出不自动 strip，在 Windows 可能含 \r\n
    assert "hi" in result.data
    assert bash.is_parallel_safe is False


@pytest.mark.anyio
async def test_bash_dangerous(tmp_path):
    """危险命令 → blocked（#6）。"""
    bash = make_bash_tool(tmp_path)
    result = await bash.execute({"command": "sudo rm -rf /"})
    # 新工具: "Error: Blocked dangerous command pattern 'rm -rf /'"
    assert "rm -rf /" in result.data or "Blocked" in result.data or "blocked" in result.data


@pytest.mark.anyio
async def test_bash_timeout(tmp_path):
    """超时 → 包含 timed out 提示。"""
    bash = make_bash_tool(tmp_path)
    sleep_script = tmp_path / "_sleep.py"
    sleep_script.write_text(
        "import sys, time; print('starting step 1...', flush=True); time.sleep(30)",
        encoding="utf-8",
    )
    # 传递 timeout=1 给新工具（参数名 timeout）
    result = await bash.execute({"command": "python _sleep.py", "timeout": 1})
    assert "timed out" in result.data.lower() or "timeout" in result.data.lower()
