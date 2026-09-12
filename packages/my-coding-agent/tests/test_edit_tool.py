from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.tools.edit import EditBlock, make_edit_tool

pytestmark = pytest.mark.anyio


async def test_edit_single_block(tmp_path: Path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="code.py",
        edits=[{"oldText": "return 1", "newText": "return 42"}],
    )
    assert "Successfully applied 1 edit(s)" in res
    assert "-    return 1" in res
    assert "+    return 42" in res
    assert f.read_text(encoding="utf-8") == "def foo():\n    return 42\n"


async def test_edit_legacy_single_params(tmp_path: Path):
    f = tmp_path / "code.py"
    f.write_text("val = 10\n", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(path="code.py", old_text="10", new_text="20")
    assert "Successfully applied 1 edit(s)" in res
    assert f.read_text(encoding="utf-8") == "val = 20\n"


async def test_edit_multiple_disjoint_blocks(tmp_path: Path):
    f = tmp_path / "multi.py"
    f.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="multi.py",
        edits=[
            {"oldText": "a = 1", "newText": "a = 100"},
            {"oldText": "c = 3", "newText": "c = 300"},
        ],
    )
    assert "Successfully applied 2 edit(s)" in res
    assert f.read_text(encoding="utf-8") == "a = 100\nb = 2\nc = 300\n"


async def test_edit_crlf_preservation(tmp_path: Path):
    f = tmp_path / "crlf.py"
    f.write_bytes(b"line1\r\nline2\r\nline3\r\n")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="crlf.py",
        edits=[{"oldText": "line2", "newText": "modified"}],
    )
    assert "Successfully applied 1 edit(s)" in res
    assert f.read_bytes() == b"line1\r\nmodified\r\nline3\r\n"


async def test_edit_bom_preservation(tmp_path: Path):
    f = tmp_path / "bom.py"
    f.write_bytes(b"\xef\xbb\xbfname = 'test'\n")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="bom.py",
        edits=[{"oldText": "'test'", "newText": "'prod'"}],
    )
    assert "Successfully applied 1 edit(s)" in res
    assert f.read_bytes() == b"\xef\xbb\xbfname = 'prod'\n"


async def test_edit_not_found_error(tmp_path: Path):
    f = tmp_path / "missing.py"
    f.write_text("alpha\nbeta\n", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="missing.py",
        edits=[{"oldText": "gamma", "newText": "delta"}],
    )
    assert "Error: 'oldText' not found in missing.py" in res


async def test_edit_multiple_occurrences_error(tmp_path: Path):
    f = tmp_path / "duplicate.py"
    f.write_text("repeat\nrepeat\n", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="duplicate.py",
        edits=[{"oldText": "repeat", "newText": "once"}],
    )
    assert "Error: 'oldText' matched 2 times" in res


async def test_edit_overlapping_regions_error(tmp_path: Path):
    f = tmp_path / "overlap.py"
    f.write_text("one two three\n", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="overlap.py",
        edits=[
            {"oldText": "one two", "newText": "1 2"},
            {"oldText": "two three", "newText": "2 3"},
        ],
    )
    assert "Error: Overlapping edit regions detected" in res


async def test_edit_file_not_found_error(tmp_path: Path):
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(path="nonexistent.py", old_text="a", new_text="b")
    assert "Error: File not found: nonexistent.py" in res


async def test_edit_directory_error(tmp_path: Path):
    d = tmp_path / "subdir"
    d.mkdir()
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(path="subdir", old_text="a", new_text="b")
    assert "Error: Path is a directory: subdir" in res


async def test_edit_binary_file_error(tmp_path: Path):
    f = tmp_path / "binary.bin"
    f.write_bytes(b"hello\x00world")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(path="binary.bin", old_text="hello", new_text="hi")
    assert "Error: Cannot edit binary file: binary.bin" in res


async def test_edit_no_params_error(tmp_path: Path):
    f = tmp_path / "code.py"
    f.write_text("test", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(path="code.py")
    assert (
        "Error: Either 'edits' or ('old_text' and 'new_text') must be provided." in res
    )

    res_empty = await tool.execute(path="code.py", edits=[])
    assert "Error: No edits provided." in res_empty


async def test_edit_empty_old_text_error(tmp_path: Path):
    f = tmp_path / "code.py"
    f.write_text("test", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="code.py",
        edits=[{"oldText": "", "newText": "replaced"}],
    )
    assert "Error: 'oldText' cannot be empty" in res


async def test_edit_delete_content(tmp_path: Path):
    f = tmp_path / "delete.py"
    f.write_text("line1\nremove_me\nline2\n", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="delete.py",
        edits=[{"oldText": "remove_me\n", "newText": ""}],
    )
    assert "Successfully applied 1 edit(s)" in res
    assert f.read_text(encoding="utf-8") == "line1\nline2\n"


async def test_edit_edit_block_instances(tmp_path: Path):
    f = tmp_path / "blocks.py"
    f.write_text("var = 1\n", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    res = await tool.execute(
        path="blocks.py",
        edits=[EditBlock(old_text="var = 1", new_text="var = 2")],
    )
    assert "Successfully applied 1 edit(s)" in res
    assert f.read_text(encoding="utf-8") == "var = 2\n"


async def test_edit_dict_call_and_is_parallel_safe(tmp_path: Path):
    f = tmp_path / "dict_call.py"
    f.write_text("hello world\n", encoding="utf-8")
    tool = make_edit_tool(tmp_path)
    assert tool.is_parallel_safe is True

    res = await tool.execute(
        {"path": "dict_call.py", "old_text": "world", "new_text": "friend"}
    )
    assert res.ok is True
    assert "Successfully applied 1 edit(s)" in str(res.data)
    assert f.read_text(encoding="utf-8") == "hello friend\n"


async def test_edit_concurrency_serialization(tmp_path: Path):
    f = tmp_path / "counter.txt"
    f.write_text("start\n", encoding="utf-8")
    queue = FileMutationQueue()
    tool = make_edit_tool(tmp_path, mutation_queue=queue)

    events: list[str] = []

    async def op1():
        events.append("start_1")
        await tool.execute(path="counter.txt", old_text="start", new_text="mid")
        await asyncio.sleep(0.01)
        events.append("end_1")

    async def op2():
        events.append("start_2")
        await tool.execute(path="counter.txt", old_text="mid", new_text="finish")
        events.append("end_2")

    await asyncio.gather(op1(), op2())

    assert len(events) == 4
