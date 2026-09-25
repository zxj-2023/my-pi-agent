"""测试 Subagent 子代理对可用工具集过滤后的专属 <tools> 与 <rules> 提示词生成。"""

from pathlib import Path

from my_agent_core.subagent_tasks import _system_for
from my_agent_core.subagents import Subagent
from my_agent_core.tools import Tool


class DummyParent:
    class DummySkillManager:
        def format_prompt(self, skills=None):
            return ""

    skill_manager = DummySkillManager()


def test_subagent_system_for_filtered_tools():
    """验证子代理仅包含其允许使用的工具提示词与规则。"""
    sub = Subagent(
        name="read_only_scout",
        description="Scout codebase without editing",
        content="You are a read-only scout.",
        file_path=Path("<test>"),
        tools=("read", "grep"),
        disallowed_tools=("write", "edit", "bash"),
    )

    def dummy_read(x: str = "") -> str:
        return x

    def dummy_grep(x: str = "") -> str:
        return x

    t_read = Tool(
        dummy_read,
        name="read",
        prompt_snippet="Read file contents",
        prompt_guidelines=["Use read to examine files instead of cat or sed."],
    )
    t_grep = Tool(
        dummy_grep,
        name="grep",
        prompt_snippet="Search file contents",
    )

    filtered_tools = [t_read, t_grep]
    prompt = _system_for(sub, DummyParent(), tools=filtered_tools)

    assert "You are a read-only scout." in prompt
    assert "<tools>" in prompt
    assert "- read: Read file contents" in prompt
    assert "- grep: Search file contents" in prompt
    # 绝不能出现 write 或 edit
    assert "- write:" not in prompt
    assert "- edit:" not in prompt

    assert "<rules>" in prompt
    assert "- Use read to examine files instead of cat or sed." in prompt
    assert "- Use edit for precise changes" not in prompt
    assert "- Use write only for new files" not in prompt
