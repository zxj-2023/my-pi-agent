from __future__ import annotations

from pathlib import Path

import pytest

from my_coding_agent.tools.ls import make_ls_tool


@pytest.mark.anyio
async def test_ls_tool_lists_files_and_directories(tmp_path: Path):
    """ls 工具正常列出文件和目录，且目录以 '/' 结尾，按字母大小写不敏感排序。"""
    (tmp_path / "b_file.txt").write_text("b", encoding="utf-8")
    (tmp_path / "A_dir").mkdir()
    (tmp_path / "c_dir").mkdir()
    (tmp_path / ".hidden_file").write_text("secret", encoding="utf-8")

    ls_tool = make_ls_tool(tmp_path)
    res = await ls_tool.execute({"path": "."})

    assert res.ok is True
    lines = str(res.data).splitlines()
    assert ".hidden_file" in lines
    assert "A_dir/" in lines
    assert "b_file.txt" in lines
    assert "c_dir/" in lines

    # 验证字母大小写不敏感排序（.hidden_file, A_dir/, b_file.txt, c_dir/）
    assert lines.index("A_dir/") < lines.index("b_file.txt")
    assert lines.index("b_file.txt") < lines.index("c_dir/")


@pytest.mark.anyio
async def test_ls_tool_empty_directory(tmp_path: Path):
    """空目录返回 (Empty directory)。"""
    ls_tool = make_ls_tool(tmp_path)
    res = await ls_tool.execute({"path": "."})
    assert res.ok is True
    assert res.data == "(Empty directory)"


@pytest.mark.anyio
async def test_ls_tool_nonexistent_and_file_path(tmp_path: Path):
    """非目录或不存在路径返回 Error。"""
    f = tmp_path / "test.txt"
    f.write_text("hello", encoding="utf-8")

    ls_tool = make_ls_tool(tmp_path)
    err_res1 = await ls_tool.execute({"path": "not_exist"})
    assert "Error: Path not found" in str(err_res1.data)

    err_res2 = await ls_tool.execute({"path": "test.txt"})
    assert "Error: Not a directory" in str(err_res2.data)


@pytest.mark.anyio
async def test_ls_tool_limit(tmp_path: Path):
    """限制返回条目数。"""
    for i in range(10):
        (tmp_path / f"file_{i:02d}.txt").write_text("content", encoding="utf-8")

    ls_tool = make_ls_tool(tmp_path)
    res = await ls_tool.execute({"path": ".", "limit": 3})
    assert res.ok is True
    lines = str(res.data).splitlines()
    # 3 files + 1 empty line + 1 truncation notice
    assert len(lines) == 5
    assert "[Output truncated: reached entry limit of 3]" in lines[-1]
