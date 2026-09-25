"""测试 7 大编码工具声明的 prompt_snippet 与 prompt_guidelines 元数据。"""

from pathlib import Path
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
