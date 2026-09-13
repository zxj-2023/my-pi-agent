from __future__ import annotations

from pathlib import Path

import pytest
from my_coding_agent.tools.find import FindResult, make_find_tool

from my_coding_agent.tools.base import DEFAULT_IGNORE_DIRS

pytestmark = pytest.mark.anyio


async def test_find_files_pattern(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "test_app.py").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("", encoding="utf-8")

    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="*.py")
    assert "src/app.py" in res or "src\\app.py" in res
    assert "src/test_app.py" in res or "src\\test_app.py" in res
    assert "README.md" not in res


async def test_find_ignores_venv(tmp_path: Path):
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "module.py").write_text("", encoding="utf-8")

    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="*.py")
    assert "module.py" not in res


async def test_find_ignores_all_default_ignore_dirs(tmp_path: Path):
    for d in DEFAULT_IGNORE_DIRS:
        ignore_dir = tmp_path / d / "subdir"
        ignore_dir.mkdir(parents=True)
        (ignore_dir / f"hidden_{d}.py").write_text("", encoding="utf-8")

    normal_dir = tmp_path / "pkg"
    normal_dir.mkdir(parents=True)
    (normal_dir / "valid.py").write_text("", encoding="utf-8")

    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="*.py")
    assert "pkg/valid.py" in res
    for d in DEFAULT_IGNORE_DIRS:
        assert f"hidden_{d}.py" not in res


async def test_find_with_subdirectory_path(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "target.py").write_text("", encoding="utf-8")
    (tmp_path / "other.py").write_text("", encoding="utf-8")

    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="*.py", path="sub")
    assert "sub/target.py" in res
    assert "other.py" not in res


async def test_find_nonexistent_path(tmp_path: Path):
    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="*.py", path="nonexistent_folder")
    assert "Error: Path not found: nonexistent_folder" in res


async def test_find_limit_truncation(tmp_path: Path):
    for i in range(10):
        (tmp_path / f"file_{i:02d}.txt").write_text("", encoding="utf-8")

    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="*.txt", limit=3)
    assert "[Truncated at limit of 3 results]" in res
    lines = [
        line for line in str(res).splitlines() if not line.startswith("[Truncated")
    ]
    assert len(lines) == 3


async def test_find_no_matches(tmp_path: Path):
    (tmp_path / "file.txt").write_text("", encoding="utf-8")
    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="*.py")
    assert "No files matching '*.py' found." in res


async def test_find_workspace_as_str(tmp_path: Path):
    (tmp_path / "test.py").write_text("", encoding="utf-8")
    tool = make_find_tool(str(tmp_path))
    res = await tool.execute(pattern="*.py")
    assert "test.py" in res


async def test_find_single_file_target(tmp_path: Path):
    f = tmp_path / "single.py"
    f.write_text("", encoding="utf-8")
    tool = make_find_tool(tmp_path)

    res_match = await tool.execute(pattern="*.py", path="single.py")
    assert "single.py" in res_match

    res_no_match = await tool.execute(pattern="*.txt", path="single.py")
    assert "No files matching '*.txt' found." in res_no_match


async def test_find_deterministic_sorting(tmp_path: Path):
    # 创建打乱顺序的文件
    (tmp_path / "c.txt").write_text("", encoding="utf-8")
    (tmp_path / "a.txt").write_text("", encoding="utf-8")
    (tmp_path / "b.txt").write_text("", encoding="utf-8")
    (tmp_path / "dir_b").mkdir()
    (tmp_path / "dir_b" / "sub.txt").write_text("", encoding="utf-8")
    (tmp_path / "dir_a").mkdir()
    (tmp_path / "dir_a" / "sub.txt").write_text("", encoding="utf-8")

    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="*.txt")
    lines = str(res).splitlines()
    assert lines == [
        "a.txt",
        "b.txt",
        "c.txt",
        "dir_a/sub.txt",
        "dir_b/sub.txt",
    ]


async def test_find_match_by_relative_path(tmp_path: Path):
    sub = tmp_path / "src" / "deep"
    sub.mkdir(parents=True)
    (sub / "nested.py").write_text("", encoding="utf-8")

    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="src/deep/*.py")
    assert "src/deep/nested.py" in res


async def test_find_result_semantics(tmp_path: Path):
    (tmp_path / "foo.py").write_text("", encoding="utf-8")
    tool = make_find_tool(tmp_path)
    res = await tool.execute(pattern="*.py")

    assert isinstance(res, FindResult)
    assert res.ok is True
    assert "foo.py" in res
    assert res == "foo.py"
    assert "foo.py" in repr(res)
    assert str(res) == "foo.py"
