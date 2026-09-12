from pathlib import Path

import pytest

from my_coding_agent.tools.read import make_read_tool


@pytest.mark.anyio
async def test_read_normal_file(tmp_path: Path):
    f = tmp_path / "hello.py"
    f.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="hello.py")
    assert "line 1\nline 2\nline 3" in res


@pytest.mark.anyio
async def test_read_with_offset_and_limit(tmp_path: Path):
    f = tmp_path / "numbers.txt"
    f.write_text("\n".join(f"line {i}" for i in range(1, 21)), encoding="utf-8")
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="numbers.txt", offset=5, limit=3)
    assert res == "line 5\nline 6\nline 7"


@pytest.mark.anyio
async def test_read_offset_out_of_bounds(tmp_path: Path):
    f = tmp_path / "small.txt"
    f.write_text("line 1\nline 2", encoding="utf-8")
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="small.txt", offset=10)
    assert "Offset 10 is beyond end of file" in res


@pytest.mark.anyio
async def test_read_binary_file(tmp_path: Path):
    bin_f = tmp_path / "blob.bin"
    bin_f.write_bytes(b"\x00\x01\x02")
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="blob.bin")
    assert "Error: Cannot read binary file" in res


@pytest.mark.anyio
async def test_read_truncation_notice(tmp_path: Path):
    f = tmp_path / "long.txt"
    f.write_text("\n".join(f"L{i}" for i in range(1, 3000)), encoding="utf-8")
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="long.txt", offset=1, limit=2500)
    assert "[Showing lines 1-2000 of 2999" in res
    assert "Use offset=2001 to continue" in res


@pytest.mark.anyio
async def test_read_nonexistent_file(tmp_path: Path):
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="not_found.txt")
    assert "Error: File not found: not_found.txt" in res


@pytest.mark.anyio
async def test_read_directory(tmp_path: Path):
    d = tmp_path / "subdir"
    d.mkdir()
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="subdir")
    assert "Error: Path is a directory: subdir" in res


@pytest.mark.anyio
async def test_read_empty_file(tmp_path: Path):
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="empty.txt")
    assert res == ""


@pytest.mark.anyio
async def test_read_byte_truncation(tmp_path: Path):
    # 60 lines, each 1000 'a' chars -> 60KB > 50KB (DEFAULT_MAX_BYTES)
    f = tmp_path / "huge_bytes.txt"
    f.write_text("\n".join("a" * 1000 for _ in range(60)), encoding="utf-8")
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="huge_bytes.txt")
    assert "[Showing lines 1-51 of 60. Use offset=52 to continue.]" in res
    assert "Use offset=52 to continue" in res


@pytest.mark.anyio
async def test_read_byte_truncation_continuation(tmp_path: Path):
    # 60 lines, each 1000 chars -> total > 50KB
    f = tmp_path / "long_lines.txt"
    f.write_text(
        "\n".join(f"line {i:03d}: " + ("x" * 990) for i in range(1, 61)),
        encoding="utf-8",
    )
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="long_lines.txt")

    assert "[Showing lines 1-51 of 60. Use offset=52 to continue.]" in res

    # Verify continuing from the suggested offset works cleanly without EOF error
    res_cont = await tool.execute(path="long_lines.txt", offset=52)
    assert "Error: Offset" not in res_cont
    assert "line 052:" in res_cont
    assert "line 060:" in res_cont


@pytest.mark.anyio
async def test_read_dict_args_and_tool_result(tmp_path: Path):
    f = tmp_path / "data.txt"
    f.write_text("line 1\nline 2\n", encoding="utf-8")
    tool = make_read_tool(tmp_path)
    res = await tool.execute({"path": "data.txt"})
    assert res.ok is True
    assert res.data == "line 1\nline 2"
    assert "line 1" in str(res.data)


@pytest.mark.anyio
async def test_read_offset_less_than_one(tmp_path: Path):
    f = tmp_path / "file.txt"
    f.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
    tool = make_read_tool(tmp_path)
    res = await tool.execute(path="file.txt", offset=0, limit=2)
    assert res == "line 1\nline 2"
