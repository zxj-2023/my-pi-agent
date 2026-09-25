"""测试工具提示词格式化模块 (format_tools_section, format_rules_section, format_cwd_section)。"""

from pathlib import Path
from my_agent_core.tools import Tool
from my_agent_core.tools.prompt import (
    format_cwd_section,
    format_rules_section,
    format_tools_section,
)


def _make_dummy_tool(
    name: str,
    snippet: str | None = None,
    guidelines: list[str] | None = None,
) -> Tool:
    def fn(x: str = "") -> str:
        return x

    return Tool(
        fn,
        name=name,
        prompt_snippet=snippet,
        prompt_guidelines=guidelines,
    )


def test_format_tools_section():
    """测试 <tools> 块生成与一句话概要。"""
    t1 = _make_dummy_tool("read", snippet="Read file contents")
    t2 = _make_dummy_tool("write", snippet="Create or overwrite files")

    section = format_tools_section([t1, t2])
    assert section.startswith("<tools>\n")
    assert section.endswith("\n</tools>")
    assert "- read: Read file contents" in section
    assert "- write: Create or overwrite files" in section
    assert (
        "In addition to the tools above, you may have access to other custom tools depending on the project." in section
    )


def test_format_tools_section_empty():
    """测试无工具或无 snippet 时的优雅兜底。"""
    section = format_tools_section([])
    assert "<tools>\n(none)\n\nIn addition to the tools above" in section


def test_format_rules_section_with_dedicated_tools():
    """当系统拥有专用 grep/find/ls 时，不应注入 bash 替代文件查找的降级规则。"""
    t_read = _make_dummy_tool(
        "read",
        snippet="Read file contents",
        guidelines=["Use read to examine files instead of cat or sed."],
    )
    t_bash = _make_dummy_tool(
        "bash",
        snippet="Execute bash commands",
        guidelines=["You can inspect PI_* environment variables for current model and session details."],
    )
    t_grep = _make_dummy_tool("grep", snippet="Grep file contents")

    rules = format_rules_section([t_read, t_bash, t_grep])
    assert rules.startswith("<rules>\n")
    assert rules.endswith("\n</rules>")
    assert "- Use read to examine files instead of cat or sed." in rules
    assert "- You can inspect PI_* environment variables for current model and session details." in rules
    # 绝对不应该出现 bash 降级搜文件规则
    assert "Use bash for file operations like ls, rg, find" not in rules
    # 必定包含通用底线规则
    assert "- Be concise in your responses" in rules
    assert "- Show file paths clearly when working with files" in rules


def test_format_rules_section_conditional_bash_fallback():
    """当系统仅有 bash 但没有 grep/find/ls 时，动态注入 bash 替代搜文件的规则。"""
    t_read = _make_dummy_tool("read", snippet="Read file contents")
    t_bash = _make_dummy_tool("bash", snippet="Execute bash commands")

    rules = format_rules_section([t_read, t_bash])
    assert "- Use bash for file operations like ls, rg, find" in rules


def test_format_rules_section_deduplication():
    """测试多工具规则去重。"""
    t1 = _make_dummy_tool("t1", guidelines=["Rule A", "Rule B"])
    t2 = _make_dummy_tool("t2", guidelines=["Rule B", "Rule C"])

    rules = format_rules_section([t1, t2], prompt_guidelines=["Rule C", "Rule D"])
    lines = [line.strip() for line in rules.splitlines() if line.startswith("- ")]

    assert lines.count("- Rule A") == 1
    assert lines.count("- Rule B") == 1
    assert lines.count("- Rule C") == 1
    assert lines.count("- Rule D") == 1


def test_format_cwd_section():
    """测试 <cwd> 路径生成及 POSIX 斜杠规范化。"""
    path = Path("D:/code/python/my-pi-agent")
    cwd_sec = format_cwd_section(path)
    assert cwd_sec == "<cwd>\nD:/code/python/my-pi-agent\n</cwd>"
