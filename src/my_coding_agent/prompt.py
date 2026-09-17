"""专业编码系统提示词与上下文自动注入。"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CODING_INSTRUCTIONS = """You are an expert coding assistant operating inside the codebase.

Core Engineering Principles:
1. Read Before Edit: Always inspect file contents with 'read' before calling 'edit'. Never guess line numbers or code blocks.
2. Surgical Edits: Keep edits concise and provide sufficient context in 'oldText' to ensure a unique match.
3. Verification Before Completion: Run tests or linters using 'bash' to verify changes before declaring work complete.
4. Minimal Changes: Do not add unsolicited refactorings, comments, or unnecessary abstractions.
"""


def build_default_coding_prompt(
    workspace: Path | str,
    global_instructions_path: Path | str | None = None,
) -> str:
    """构建专业编码系统提示词，自动扫描并注入项目指导文件。

    Args:
        workspace: 工作区目录路径（支持 Path 或 str）。
        global_instructions_path: 可选的全局规则文件（如 ~/.pi/agent/AGENTS.md）。

    Returns:
        包含工程规范、工作区路径以及项目上下文的完整系统提示词。
    """
    workspace_path = Path(workspace).resolve()
    sections = [
        DEFAULT_CODING_INSTRUCTIONS,
        f"Workspace Directory: {workspace_path}",
    ]

    injected_contexts = []
    seen_paths: set[str] = set()

    # 1. 注入全局指令文件（若存在）
    if global_instructions_path is not None:
        gp = Path(global_instructions_path).resolve()
        if gp.is_file():
            try:
                content = gp.read_text(encoding="utf-8", errors="replace")
                injected_contexts.append(f'<project_instructions path="{gp}">\n{content}\n</project_instructions>')
                seen_paths.add(str(gp))
            except Exception:
                logger.debug("Failed to read global context file: %s", gp, exc_info=True)

    # 2. 扫描并注入工作区局部指导文件
    context_files = ["AGENTS.override.md", "AGENTS.md", "CLAUDE.md", "README.md"]
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
        sections.append("<project_context>\n" + "\n\n".join(injected_contexts) + "\n</project_context>")

    return "\n\n".join(sections)
