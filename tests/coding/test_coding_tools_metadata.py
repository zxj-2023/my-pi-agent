"""测试 7 大编码工具声明的 prompt_snippet 与 prompt_guidelines 元数据。"""

from pathlib import Path

import pytest
from my_coding_agent.tools import (
    make_bash_tool,
    make_edit_tool,
    make_find_tool,
    make_grep_tool,
    make_ls_tool,
    make_read_tool,
    make_write_tool,
)


def test_coding_tools_metadata(tmp_path: Path):
    """验证所有 7 大工作区编码工具均携带对标 Pi 原厂的 snippet 与 guidelines。"""
    t_read = make_read_tool(tmp_path)
    assert t_read.prompt_snippet == "Read file contents"
    assert t_read.prompt_guidelines == ["Use read to examine files instead of cat or sed."]

    t_write = make_write_tool(tmp_path)
    assert t_write.prompt_snippet == "Create or overwrite files"
    assert t_write.prompt_guidelines == ["Use write only for new files or complete rewrites."]

    t_edit = make_edit_tool(tmp_path)
    assert t_edit.prompt_snippet == (
        "Make precise file edits with exact text replacement, including multiple disjoint edits in one call"
    )
    assert len(t_edit.prompt_guidelines) == 4
    assert "Use edit for precise changes (edits[].oldText must match exactly)" in t_edit.prompt_guidelines
    assert (
        "Keep edits[].oldText as small as possible while still being unique in the file. Do not pad with large unchanged regions."
        in t_edit.prompt_guidelines
    )

    t_bash = make_bash_tool(tmp_path)
    assert t_bash.prompt_snippet == "Execute bash commands (ls, grep, find, etc.)"
    assert t_bash.prompt_guidelines == [
        "You can inspect PI_* environment variables for current model and session details."
    ]

    t_grep = make_grep_tool(tmp_path)
    assert t_grep.prompt_snippet == "Search file contents for patterns (respects .gitignore)"
    assert t_grep.prompt_guidelines == []

    t_find = make_find_tool(tmp_path)
    assert t_find.prompt_snippet == "Find files by glob pattern (respects .gitignore)"
    assert t_find.prompt_guidelines == []

    t_ls = make_ls_tool(tmp_path)
    assert t_ls.prompt_snippet == "List directory contents"
    assert t_ls.prompt_guidelines == []


@pytest.mark.anyio
async def test_coding_tools_argument_aliases(tmp_path: Path):
    """验证 7 大编码工具对常用别名 (filePath/text/cmd/query/directory 等) 的无缝兼容支持。"""
    t_read = make_read_tool(tmp_path)
    t_write = make_write_tool(tmp_path)
    t_edit = make_edit_tool(tmp_path)
    t_bash = make_bash_tool(tmp_path)
    t_grep = make_grep_tool(tmp_path)
    t_find = make_find_tool(tmp_path)
    t_ls = make_ls_tool(tmp_path)

    # 1. write: filePath + text 别名
    w_res = await t_write.execute({"filePath": "sample.txt", "text": "hello python"})
    assert w_res.ok is True
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "hello python"

    # 2. read: filePath 别名
    r_res = await t_read.execute({"filePath": "sample.txt"})
    assert r_res.ok is True
    assert "hello python" in r_res.data

    # 3. edit: filePath 别名
    e_res = await t_edit.execute({"filePath": "sample.txt", "edits": [{"oldText": "python", "newText": "tau"}]})
    assert e_res.ok is True
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "hello tau"

    # 4. grep: query + directory 别名
    g_res = await t_grep.execute({"query": "tau", "directory": "."})
    assert g_res.ok is True
    assert "sample.txt" in g_res.data

    # 5. find: glob + directory 别名
    f_res = await t_find.execute({"glob": "*.txt", "directory": "."})
    assert f_res.ok is True
    assert "sample.txt" in f_res.data

    # 6. ls: directory 别名
    ls_res = await t_ls.execute({"directory": "."})
    assert ls_res.ok is True
    assert "sample.txt" in ls_res.data

    # 7. bash: cmd 别名
    b_res = await t_bash.execute({"cmd": "echo 'alias test'"})
    assert b_res.ok is True
    assert "alias test" in b_res.data
