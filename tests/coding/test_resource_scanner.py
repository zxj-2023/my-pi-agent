"""资源扫描器单元测试。"""

from pathlib import Path

from my_coding_agent.paths import AgentPaths
from my_coding_agent.resource_scanner import get_all_skill_dirs, scan_loaded_resources


def test_scan_loaded_resources_structure(tmp_path: Path):
    paths = AgentPaths(home=tmp_path / "home")
    res = scan_loaded_resources(tmp_path, paths)
    assert "context" in res
    assert "skills" in res
    assert "prompts" in res
    assert "extensions" in res
    assert isinstance(res["context"], list)
    assert isinstance(res["skills"], list)
    assert isinstance(res["prompts"], list)
    assert isinstance(res["extensions"], list)


def test_scan_loaded_resources_with_local_files(tmp_path: Path):
    paths = AgentPaths(home=tmp_path / "home")
    # 创建本地 context 文件
    (tmp_path / "AGENTS.md").write_text("# Local Agents", encoding="utf-8")
    # 创建本地 prompts 目录
    p_dir = tmp_path / "prompts"
    p_dir.mkdir(parents=True)
    (p_dir / "review-loop.md").write_text("# Prompt", encoding="utf-8")
    # 创建本地 skills 目录
    s_dir = tmp_path / ".skills" / "custom-skill"
    s_dir.mkdir(parents=True)
    (s_dir / "SKILL.md").write_text("# Skill", encoding="utf-8")

    res = scan_loaded_resources(tmp_path, paths)
    assert "AGENTS.md" in res["context"]
    assert "/review-loop" in res["prompts"]
    assert "custom-skill" in res["skills"]


def test_get_all_skill_dirs_discovers_skills(tmp_path: Path):
    paths = AgentPaths(home=tmp_path / "home")
    s_dir = tmp_path / ".skills"
    s_dir.mkdir(parents=True)
    dirs = get_all_skill_dirs(tmp_path, paths)
    assert any(d.resolve() == s_dir.resolve() for d in dirs)
