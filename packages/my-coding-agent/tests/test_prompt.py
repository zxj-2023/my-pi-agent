"""专业编码系统提示词与上下文注入测试。"""

from pathlib import Path

from my_coding_agent.prompt import (
    build_default_coding_prompt,
)


def test_build_prompt_contains_core_guidelines(tmp_path: Path):
    prompt = build_default_coding_prompt(tmp_path)
    assert "expert coding assistant" in prompt
    assert "read before edit" in prompt.lower()
    assert str(tmp_path.resolve()) in prompt


def test_build_prompt_injects_project_context(tmp_path: Path):
    agents_doc = tmp_path / "AGENTS.md"
    agents_doc.write_text("# Project Rules\nAlways use UV.", encoding="utf-8")
    prompt = build_default_coding_prompt(tmp_path)
    assert "<project_context>" in prompt
    assert "Always use UV." in prompt
    assert f'<project_instructions path="{agents_doc.resolve()}">' in prompt


def test_build_prompt_supports_str_workspace(tmp_path: Path):
    prompt = build_default_coding_prompt(str(tmp_path))
    assert str(tmp_path.resolve()) in prompt


def test_build_prompt_without_context_files_has_no_project_context(tmp_path: Path):
    prompt = build_default_coding_prompt(tmp_path)
    assert "<project_context>" not in prompt


def test_build_prompt_injects_multiple_context_files(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("Agents guide", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Claude guide", encoding="utf-8")
    (tmp_path / "README.md").write_text("Readme guide", encoding="utf-8")
    prompt = build_default_coding_prompt(tmp_path)
    assert "Agents guide" in prompt
    assert "Claude guide" in prompt
    assert "Readme guide" in prompt
    assert prompt.count("<project_instructions") == 3


def test_build_prompt_handles_unreadable_file(tmp_path: Path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("Agents guide", encoding="utf-8")

    def mock_read_text(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_text", mock_read_text)
    prompt = build_default_coding_prompt(tmp_path)
    assert "<project_context>" not in prompt
