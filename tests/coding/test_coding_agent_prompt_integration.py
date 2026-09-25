"""测试 CodingAgent 初始化与系统提示词（<tools>, <rules>, <cwd>）全链路集成。"""

from pathlib import Path
from my_coding_agent import CodingAgent
from my_agent_core.session import Session


class DummyLLM:
    pass


def test_coding_agent_system_prompt_has_tools_and_rules(tmp_path: Path):
    """验证 CodingAgent 默认生成的系统提示词完整包含 7 大编码工具的 <tools>、<rules> 与 <cwd>。"""
    session = Session(path=tmp_path / "session.jsonl", cwd=str(tmp_path))
    ca = CodingAgent(
        workspace=tmp_path,
        llm=DummyLLM(),
        session=session,
    )

    sys_msg = ca.agent.messages[0]
    assert sys_msg.role == "system"
    content = sys_msg.content

    # 1. 验证 Preamble
    assert "You are an expert coding assistant operating inside my-pi-agent" in content

    # 2. 验证 <tools> 包含 7 大核心工具
    assert "<tools>" in content
    assert "- read: Read file contents" in content
    assert "- write: Create or overwrite files" in content
    assert "- edit: Make precise file edits with exact text replacement" in content
    assert "- bash: Execute bash commands" in content
    assert "- grep: Search file contents" in content
    assert "- find: Find files by glob pattern" in content
    assert "- ls: List directory contents" in content

    # 3. 验证 <rules> 包含工具规则与通用规则
    assert "<rules>" in content
    assert "- Use read to examine files instead of cat or sed." in content
    assert "- Use write only for new files or complete rewrites." in content
    assert "- Use edit for precise changes (edits[].oldText must match exactly)" in content
    assert "- You can inspect PI_* environment variables for current model and session details." in content
    assert "- Be concise in your responses" in content
    assert "- Show file paths clearly when working with files" in content

    # 4. 验证 <cwd>
    normalized = str(tmp_path.resolve()).replace("\\", "/")
    assert f"<cwd>\n{normalized}\n</cwd>" in content
