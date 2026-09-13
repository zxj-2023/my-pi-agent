from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.tools.write import make_write_tool

pytestmark = pytest.mark.anyio


async def test_write_creates_file_and_parents(tmp_path: Path):
    tool = make_write_tool(tmp_path)
    res = await tool.execute(path="nested/sub/app.py", content="print('hello')\n")
    assert "Successfully wrote" in res
    target = tmp_path / "nested/sub/app.py"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "print('hello')\n"


async def test_write_with_mutation_queue(tmp_path: Path):
    queue = FileMutationQueue()
    tool = make_write_tool(tmp_path, mutation_queue=queue)
    res = await tool.execute(path="test.txt", content="abc")
    assert "3 bytes" in res
    target = tmp_path / "test.txt"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "abc"


async def test_write_overwrites_existing_file(tmp_path: Path):
    f = tmp_path / "existing.txt"
    f.write_text("old content", encoding="utf-8")
    tool = make_write_tool(tmp_path)
    res = await tool.execute(path="existing.txt", content="new content")
    assert "Successfully wrote" in res
    assert f.read_text(encoding="utf-8") == "new content"


async def test_write_empty_content(tmp_path: Path):
    tool = make_write_tool(tmp_path)
    res = await tool.execute(path="empty.txt", content="")
    assert "0 bytes (0 lines)" in res
    target = tmp_path / "empty.txt"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""


async def test_write_multiline_content(tmp_path: Path):
    tool = make_write_tool(tmp_path)
    content = "line 1\nline 2\nline 3\n"
    res = await tool.execute(path="multi.txt", content=content)
    assert "3 lines" in res
    target = tmp_path / "multi.txt"
    assert target.read_text(encoding="utf-8") == content


async def test_write_utf8_encoding(tmp_path: Path):
    tool = make_write_tool(tmp_path)
    content = "你好，世界！\n"
    expected_bytes = len(content.encode("utf-8"))
    res = await tool.execute(path="utf8.txt", content=content)
    assert f"{expected_bytes} bytes" in res
    assert "1 lines" in res
    target = tmp_path / "utf8.txt"
    assert target.read_text(encoding="utf-8") == content


async def test_write_to_directory_error(tmp_path: Path):
    dir_path = tmp_path / "some_dir"
    dir_path.mkdir()
    tool = make_write_tool(tmp_path)
    res = await tool.execute(path="some_dir", content="not allowed")
    assert "Error" in res


async def test_write_dict_args_and_kwargs(tmp_path: Path):
    tool = make_write_tool(tmp_path)
    # dict args
    res_dict = await tool.execute({"path": "dict_call.txt", "content": "hello from dict"})
    assert res_dict.ok is True
    assert "Successfully wrote" in str(res_dict.data)
    assert (tmp_path / "dict_call.txt").read_text(encoding="utf-8") == "hello from dict"

    # kwargs call
    res_kw = await tool.execute(path="kw_call.txt", content="hello from kwargs")
    assert res_kw.ok is True
    assert "Successfully wrote" in str(res_kw.data)
    assert (tmp_path / "kw_call.txt").read_text(encoding="utf-8") == "hello from kwargs"


async def test_write_is_parallel_safe(tmp_path: Path):
    tool = make_write_tool(tmp_path)
    assert tool.is_parallel_safe is True


async def test_write_concurrent_different_files(tmp_path: Path):
    queue = FileMutationQueue()
    tool = make_write_tool(tmp_path, mutation_queue=queue)

    results = await asyncio.gather(
        tool.execute(path="a.txt", content="content a"),
        tool.execute(path="b.txt", content="content b"),
        tool.execute(path="c/d.txt", content="content cd"),
    )

    for r in results:
        assert "Successfully wrote" in r
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "content a"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "content b"
    assert (tmp_path / "c/d.txt").read_text(encoding="utf-8") == "content cd"


async def test_write_concurrent_same_file_serialized(tmp_path: Path):
    queue = FileMutationQueue()
    tool = make_write_tool(tmp_path, mutation_queue=queue)

    events: list[str] = []

    async def write_op(tag: str, text: str):
        events.append(f"start_{tag}")
        await tool.execute(path="shared.txt", content=text)
        await asyncio.sleep(0.01)
        events.append(f"end_{tag}")

    await asyncio.gather(
        write_op("op1", "first"),
        write_op("op2", "second"),
    )

    # Serialized execution: one completes before another
    assert len(events) == 4
    assert (tmp_path / "shared.txt").read_text(encoding="utf-8") in ("first", "second")
