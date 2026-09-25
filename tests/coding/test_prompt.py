"""专业编码系统提示词与上下文注入测试（对标 Pi 原厂体系）。"""

from pathlib import Path

from my_agent_core.tools import Tool
from my_coding_agent.prompt import (
    build_default_coding_prompt,
)


def test_build_prompt_contains_core_guidelines(tmp_path: Path):
    prompt = build_default_coding_prompt(tmp_path)
    assert "expert coding assistant operating inside my-pi-agent" in prompt
    assert "<tools>" in prompt
    assert "- read: Read file contents" in prompt
    assert "- edit: Make precise file edits" in prompt
    assert "<rules>" in prompt
    assert "- Use edit for precise changes" in prompt
    assert "- Be concise in your responses" in prompt
    assert "<cwd>" in prompt
    normalized_path = str(tmp_path.resolve()).replace("\\", "/")
    assert f"<cwd>\n{normalized_path}\n</cwd>" in prompt


def test_build_prompt_with_custom_tools(tmp_path: Path):
    def echo_fn(msg: str = "") -> str:
        return msg

    custom_tool = Tool(
        echo_fn,
        name="echo",
        prompt_snippet="Echo input message",
        prompt_guidelines=["Always echo safely."],
    )
    prompt = build_default_coding_prompt(tmp_path, tools=[custom_tool])
    assert "- echo: Echo input message" in prompt
    assert "- Always echo safely." in prompt
    # 默认 7 大工具不应在其中（仅有 custom_tool）
    assert "- read: Read file contents" not in prompt


def test_build_prompt_injects_project_context(tmp_path: Path):
    agents_doc = tmp_path / "AGENTS.md"
    agents_doc.write_text("# Project Rules\nAlways use UV.", encoding="utf-8")
    prompt = build_default_coding_prompt(tmp_path)
    assert "<project_context>" in prompt
    assert "Project-specific instructions and guidelines:" in prompt
    assert "Always use UV." in prompt
    assert f'<project_instructions path="{agents_doc.resolve()}">' in prompt


def test_build_prompt_supports_str_workspace(tmp_path: Path):
    prompt = build_default_coding_prompt(str(tmp_path))
    normalized_path = str(tmp_path.resolve()).replace("\\", "/")
    assert f"<cwd>\n{normalized_path}\n</cwd>" in prompt


def test_build_prompt_without_context_files_has_no_project_context(tmp_path: Path):
    prompt = build_default_coding_prompt(tmp_path)
    assert "<project_context>" not in prompt


def test_build_prompt_injects_multiple_context_files(tmp_path: Path):
    (tmp_path / "AGENTS.override.md").write_text("Override guide", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Agents guide", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Claude guide", encoding="utf-8")
    (tmp_path / "README.md").write_text("Readme guide", encoding="utf-8")
    prompt = build_default_coding_prompt(tmp_path)
    assert "Override guide" in prompt
    assert "Agents guide" in prompt
    assert "Readme guide" in prompt
    # CLAUDE.md is intentionally ignored and not injected into context
    assert "Claude guide" not in prompt
    assert prompt.count("<project_instructions") == 3


def test_build_prompt_handles_unreadable_file(tmp_path: Path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("Agents guide", encoding="utf-8")

    def mock_read_text(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_text", mock_read_text)
    prompt = build_default_coding_prompt(tmp_path)
    assert "<project_context>" not in prompt
