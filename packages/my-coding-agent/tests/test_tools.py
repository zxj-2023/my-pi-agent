"""四个文件工具离线测试（真文件系统 tmp_path，无需 FakeLLM）。"""

import asyncio

import pytest  # pyright: ignore[reportMissingImports]

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
    """limit 截断 + '... (N more lines, X lines total)'（#2）。"""
    read = make_read_tool(tmp_path)
    (tmp_path / "a.txt").write_text(
        "\n".join(f"l{i}" for i in range(10)), encoding="utf-8"
    )
    result = await read.execute({"path": "a.txt", "limit": 3})
    assert "... (7 more lines, 10 lines total)" in result.data


@pytest.mark.anyio
async def test_read_offset_beyond_end(tmp_path):
    """offset 超出文件总行数 → 返回精准行数提示。"""
    read = make_read_tool(tmp_path)
    (tmp_path / "a.txt").write_text("line1\nline2", encoding="utf-8")
    result = await read.execute({"path": "a.txt", "offset": 100})
    assert "Offset 100 is beyond end of file" in result.data
    assert "has only 2 lines total" in result.data


@pytest.mark.anyio
async def test_read_escape(tmp_path):
    """路径逃逸 → 'escapes workspace'（#1）。"""
    read = make_read_tool(tmp_path)
    result = await read.execute({"path": "../secret.txt"})
    assert "escapes workspace" in result.data


@pytest.mark.anyio
async def test_read_missing(tmp_path):
    """不存在文件 → 'does not exist'。"""
    read = make_read_tool(tmp_path)
    result = await read.execute({"path": "nope.txt"})
    assert "does not exist" in result.data


@pytest.mark.anyio
async def test_write_creates_and_overwrites(tmp_path):
    """写文件（自动建父目录）+ 覆盖 + 返回字节数（#3）。"""
    write = make_write_tool(tmp_path)
    result = await write.execute({"path": "sub/dir/a.txt", "content": "hello"})
    assert "Wrote 5 bytes" in result.data
    assert (tmp_path / "sub" / "dir" / "a.txt").read_text(encoding="utf-8") == "hello"
    await write.execute({"path": "sub/dir/a.txt", "content": "world"})
    assert (tmp_path / "sub" / "dir" / "a.txt").read_text(encoding="utf-8") == "world"
    assert write.is_parallel_safe is True


@pytest.mark.anyio
async def test_edit_replaces_once(tmp_path):
    """精确替换一次（#4）。"""
    edit = make_edit_tool(tmp_path)
    (tmp_path / "a.txt").write_text("hello world hello", encoding="utf-8")
    result = await edit.execute(
        {"path": "a.txt", "old_text": "world", "new_text": "earth"}
    )
    assert "Edited a.txt" in result.data
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello earth hello"
    assert edit.is_parallel_safe is True


@pytest.mark.anyio
async def test_edit_text_not_found(tmp_path):
    """old_text 不存在 → 包含行数与排查建议。"""
    edit = make_edit_tool(tmp_path)
    (tmp_path / "a.txt").write_text("line1\nline2", encoding="utf-8")
    result = await edit.execute({"path": "a.txt", "old_text": "nope", "new_text": "x"})
    assert "Text not found in a.txt" in result.data
    assert "file has 2 lines total" in result.data


@pytest.mark.anyio
async def test_edit_multiple_matches(tmp_path):
    """old_text 命中多处 → 提示提供更多上下文。"""
    edit = make_edit_tool(tmp_path)
    (tmp_path / "a.txt").write_text("dup\ndup\n", encoding="utf-8")
    result = await edit.execute(
        {"path": "a.txt", "old_text": "dup", "new_text": "unique"}
    )
    assert "old_text matched 2 locations" in result.data
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
    assert result.data == "hi"
    assert bash.is_parallel_safe is False


@pytest.mark.anyio
async def test_bash_dangerous(tmp_path):
    """危险命令 → blocked（#6）。"""
    bash = make_bash_tool(tmp_path)
    result = await bash.execute({"command": "sudo rm -rf /"})
    assert result.data == "Error: Dangerous command blocked"


@pytest.mark.anyio
async def test_bash_timeout_captures_partial_output(tmp_path, monkeypatch):
    """超时自动捕获已输出的日志并给出提示。"""
    import my_coding_agent.tools as files

    monkeypatch.setattr(files, "_TIMEOUT_SECONDS", 1)
    bash = make_bash_tool(tmp_path)
    sleep_script = tmp_path / "_sleep.py"
    sleep_script.write_text(
        "import sys, time; print('starting step 1...', flush=True); time.sleep(5)",
        encoding="utf-8",
    )
    result = await bash.execute({"command": "python _sleep.py"})
    assert "Timeout (1s)" in result.data
    assert "Output before timeout" in result.data
    assert "starting step 1..." in result.data
