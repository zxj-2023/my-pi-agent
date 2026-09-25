"""专业编码系统提示词与上下文自动注入（对标 Pi 原厂体系）。"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from my_agent_core.tools import (
    Tool,
    format_cwd_section,
    format_rules_section,
    format_tools_section,
)

logger = logging.getLogger(__name__)

DEFAULT_PREAMBLE = (
    "You are an expert coding assistant operating inside my-pi-agent, a coding agent harness. "
    "You help users by reading files, executing commands, editing code, and writing new files."
)


def build_default_coding_prompt(
    workspace: Path | str,
    tools: Sequence[Tool] | None = None,
    global_instructions_path: Path | str | None = None,
    custom_preamble: str | None = None,
) -> str:
    """构建专业编码系统提示词，自动整合 <tools>、<rules>、<cwd> 并扫描注入项目指导文件。

    Args:
        workspace: 工作区目录路径（支持 Path 或 str）。
        tools: 当前已激活的工具列表（用于动态生成 <tools> 与 <rules>）。若为 None，自动构建 7 大编码工具。
        global_instructions_path: 可选的全局规则文件（如 ~/.my-pi-agent/AGENTS.md）。
        custom_preamble: 可选的自定义前导文本（缺省使用 DEFAULT_PREAMBLE）。

    Returns:
        对标 Pi 原厂规范的完整结构化系统提示词。
    """
    workspace_path = Path(workspace).resolve()

    # 1. 解析可用工具集
    if tools is None:
        from my_coding_agent.tools import build_coding_tools

        active_tools = build_coding_tools(workspace_path)
    else:
        active_tools = list(tools)

    sections: list[str] = [
        custom_preamble or DEFAULT_PREAMBLE,
        format_tools_section(active_tools),
        format_rules_section(active_tools),
        format_cwd_section(workspace_path),
    ]

    injected_contexts = []
    seen_paths: set[str] = set()

    # 2. 注入全局指令文件（若存在）
    if global_instructions_path is not None:
        gp = Path(global_instructions_path).resolve()
        if gp.is_file():
            try:
                content = gp.read_text(encoding="utf-8", errors="replace")
                injected_contexts.append(f'<project_instructions path="{gp}">\n{content}\n</project_instructions>')
                seen_paths.add(str(gp))
            except Exception:
                logger.debug("Failed to read global context file: %s", gp, exc_info=True)

    # 3. 扫描并注入工作区局部指导文件（忽略 CLAUDE.md，仅保留 AGENTS 体系与 README）
    context_files = ["AGENTS.override.md", "AGENTS.md", "README.md"]
    for fname in context_files:
        fpath = workspace_path / fname
        if fpath.is_file() and str(fpath.resolve()) not in seen_paths:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                injected_contexts.append(f'<project_instructions path="{fpath}">\n{content}\n</project_instructions>')
                seen_paths.add(str(fpath.resolve()))
            except Exception:
                logger.debug("Failed to read context file: %s", fpath, exc_info=True)

    if injected_contexts:
        sections.append(
            "<project_context>\nProject-specific instructions and guidelines:\n\n"
            + "\n\n".join(injected_contexts)
            + "\n</project_context>"
        )

    return "\n\n".join(sections)
