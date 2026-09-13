from __future__ import annotations

from pathlib import Path

import pytest

from my_coding_agent.tools.grep import make_grep_tool

pytestmark = pytest.mark.anyio


async def test_grep_literal(tmp_path: Path):
    f = tmp_path / "hello.py"
    f.write_text(
        "def find_me():\n    pass\ndef other():\n    pass\n",
        encoding="utf-8",
    )
    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern="find_me")
    assert "hello.py:1: def find_me():" in res


async def test_grep_regex(tmp_path: Path):
    f = tmp_path / "app.py"
    f.write_text("var_123 = 1\nvar_abc = 2\n", encoding="utf-8")
    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern=r"var_\d+", regex=True)
    assert "app.py:1: var_123 = 1" in res
    assert "var_abc" not in res


async def test_grep_ignores_cache_dirs(tmp_path: Path):
    cache_dir = tmp_path / ".venv/lib"
    cache_dir.mkdir(parents=True)
    (cache_dir / "pkg.py").write_text("secret_token = 'xyz'", encoding="utf-8")
    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern="secret_token")
    assert "No matches found" in res


async def test_grep_case_sensitive(tmp_path: Path):
    f = tmp_path / "case.txt"
    f.write_text("FooBar\nfoobar\nFOOBAR\n", encoding="utf-8")
    tool = make_grep_tool(tmp_path)

    # case_sensitive = False (default) matches all
    res_ci = await tool.execute(pattern="FooBar")
    assert "case.txt:1: FooBar" in res_ci
    assert "case.txt:2: foobar" in res_ci
    assert "case.txt:3: FOOBAR" in res_ci

    # case_sensitive = True matches exact case only
    res_cs = await tool.execute(pattern="FooBar", case_sensitive=True)
    assert "case.txt:1: FooBar" in res_cs
    assert "case.txt:2: foobar" not in res_cs
    assert "case.txt:3: FOOBAR" not in res_cs


async def test_grep_max_matches(tmp_path: Path):
    f = tmp_path / "numbers.txt"
    f.write_text("\n".join(f"target_{i}" for i in range(20)), encoding="utf-8")
    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern="target_", max_matches=5)
    assert "[Reached maximum limit of 5 matches]" in res
    assert "numbers.txt:5: target_4" in res
    assert "numbers.txt:6: target_5" not in res


async def test_grep_glob_filter(tmp_path: Path):
    py_f = tmp_path / "code.py"
    py_f.write_text("keyword = 1\n", encoding="utf-8")
    txt_f = tmp_path / "notes.txt"
    txt_f.write_text("keyword = 2\n", encoding="utf-8")

    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern="keyword", glob_filter="*.py")
    assert "code.py:1: keyword = 1" in res
    assert "notes.txt" not in res


async def test_grep_single_file(tmp_path: Path):
    f = tmp_path / "single.py"
    f.write_text("target_function()\nother()\n", encoding="utf-8")
    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern="target_function", path="single.py")
    assert "single.py:1: target_function()" in res


async def test_grep_binary_file(tmp_path: Path):
    bin_f = tmp_path / "blob.bin"
    bin_f.write_bytes(b"hello\x00world\x00")
    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern="hello")
    assert "No matches found" in res


async def test_grep_nonexistent_path(tmp_path: Path):
    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern="hello", path="does_not_exist")
    assert "Error: Path not found: does_not_exist" in res


async def test_grep_invalid_regex(tmp_path: Path):
    f = tmp_path / "sample.txt"
    f.write_text("hello\n", encoding="utf-8")
    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern="[unclosed-regex", regex=True)
    assert "Error: Invalid regular expression:" in res


async def test_grep_workspace_as_str(tmp_path: Path):
    f = tmp_path / "test.py"
    f.write_text("match_me = True\n", encoding="utf-8")
    tool = make_grep_tool(str(tmp_path))
    res = await tool.execute(pattern="match_me")
    assert "test.py:1: match_me = True" in res


async def test_grep_no_matches(tmp_path: Path):
    f = tmp_path / "empty.py"
    f.write_text("nothing here\n", encoding="utf-8")
    tool = make_grep_tool(tmp_path)
    res = await tool.execute(pattern="missing_needle")
    assert "No matches found for pattern 'missing_needle'." in res
