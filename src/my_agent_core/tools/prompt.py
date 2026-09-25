"""工具提示词与规则格式化器（对标 Pi 原厂 system-prompt.js 规范）。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_agent_core.tools.core import Tool


def format_tools_section(tools: Sequence[Tool]) -> str:
    """构建 <tools> 动作空间清单块。

    遍历当前已激活工具，提取 prompt_snippet 生成精简列表。
    末尾附带动态扩展说明，确保第三方扩展与 MCP 工具合法融入心智模型。
    """
    visible_tools = [t for t in tools if t.prompt_snippet]
    if visible_tools:
        tools_text = "\n".join(f"- {t.name}: {t.prompt_snippet}" for t in visible_tools)
    else:
        tools_text = "(none)"

    footer = "In addition to the tools above, you may have access to other custom tools depending on the project."
    return f"<tools>\n{tools_text}\n\n{footer}\n</tools>"


def format_rules_section(
    tools: Sequence[Tool],
    prompt_guidelines: Sequence[str] | None = None,
) -> str:
    """构建 <rules> 工具级决策准则与避坑指南块。

    1. 条件互斥：若仅有 bash 但无 grep/find/ls，动态注入 bash 替代搜文件的规则；
    2. 收集所有已激活工具自带的 prompt_guidelines 并执行去重；
    3. 收集外部传入的 prompt_guidelines；
    4. 注入通用底线规则（Be concise in your responses 等）。
    """
    rules: list[str] = []
    seen: set[str] = set()

    def add_rule(rule: str) -> None:
        normalized = rule.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        rules.append(f"- {normalized}")

    tool_names = {t.name for t in tools}
    has_bash = "bash" in tool_names or "powershell" in tool_names
    has_grep = "grep" in tool_names
    has_find = "find" in tool_names
    has_ls = "ls" in tool_names

    # 动态互斥规则：当且仅当无专用文件检索工具时，才提示使用 shell 代劳
    if has_bash and not (has_grep or has_find or has_ls):
        add_rule("Use bash for file operations like ls, rg, find")

    # 汇聚已激活工具自带规则
    for t in tools:
        for guideline in t.prompt_guidelines:
            add_rule(guideline)

    # 汇聚外部传入规则
    if prompt_guidelines:
        for guideline in prompt_guidelines:
            add_rule(guideline)

    # 注入通用底线规则（对标 Pi 原厂 buildRules）
    add_rule("Be concise in your responses")
    add_rule("Show file paths clearly when working with files")

    return "<rules>\n" + "\n".join(rules) + "\n</rules>"


def format_cwd_section(workspace: Path | str) -> str:
    """构建 <cwd> 工作区路径块，强制规范化为 POSIX 斜杠路径。"""
    normalized_path = str(Path(workspace).resolve()).replace("\\", "/")
    return f"<cwd>\n{normalized_path}\n</cwd>"
