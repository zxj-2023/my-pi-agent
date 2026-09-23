"""AgentPaths 路径调度中心单测集 (Task 1)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from my_coding_agent.paths import AgentPaths


def test_agent_paths_default_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    resolved_tmp = tmp_path.resolve()
    monkeypatch.delenv("MY_AGENT_HOME", raising=False)
    monkeypatch.setenv("USERPROFILE", str(resolved_tmp))
    monkeypatch.setenv("HOME", str(resolved_tmp))
    monkeypatch.setattr(Path, "home", lambda: resolved_tmp)

    paths = AgentPaths()
    assert paths.home == resolved_tmp / ".my-pi-agent"
    assert paths.agents_home == resolved_tmp / ".agents"
    assert paths.auth_path == resolved_tmp / ".my-pi-agent" / "auth.json"
    assert paths.auth_lock_path == resolved_tmp / ".my-pi-agent" / "auth.json.lock"
    assert paths.settings_path == resolved_tmp / ".my-pi-agent" / "settings.json"
    assert paths.sessions_dir == resolved_tmp / ".my-pi-agent" / "sessions"
    assert paths.skills_dir == resolved_tmp / ".my-pi-agent" / "skills"
    assert paths.prompts_dir == resolved_tmp / ".my-pi-agent" / "prompts"
    assert paths.themes_dir == resolved_tmp / ".my-pi-agent" / "themes"
    assert paths.extensions_dir == resolved_tmp / ".my-pi-agent" / "extensions"
    assert paths.logs_dir == resolved_tmp / ".my-pi-agent" / "logs"


def test_agent_paths_custom_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom_home = tmp_path / "custom_agent"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    paths = AgentPaths()
    assert paths.home == custom_home.resolve()


def test_agent_paths_explicit_init(tmp_path: Path) -> None:
    custom_home = tmp_path / "explicit_home"
    custom_agents = tmp_path / "explicit_agents"
    paths = AgentPaths(home=custom_home, agents_home=custom_agents)
    assert paths.home == custom_home
    assert paths.agents_home == custom_agents


def test_slugify_path_normal_and_long(tmp_path: Path) -> None:
    p = tmp_path / "code" / "my-project"
    slug = AgentPaths._slugify_path(p, max_length=48)
    assert "my-project" in slug
    assert len(slug) <= 48

    # 超长路径截断测试
    long_p = tmp_path / ("a" * 20) / ("b" * 20) / ("c" * 20) / "my-target"
    long_slug = AgentPaths._slugify_path(long_p, max_length=30)
    assert len(long_slug) <= 30
    assert "my-target" in long_slug


def test_slugify_path_root_or_empty() -> None:
    # 根路径退避测试
    root_p = Path(Path().resolve().anchor)
    slug = AgentPaths._slugify_path(root_p)
    assert slug == "project" or len(slug) > 0


def test_slugify_path_special_characters(tmp_path: Path) -> None:
    special_p = tmp_path / "my @special #project$dir!"
    slug = AgentPaths._slugify_path(special_p)
    assert "my-special-project-dir" in slug
    assert "@" not in slug
    assert "#" not in slug
    assert "$" not in slug
    assert "!" not in slug


def test_slugify_path_relative_to_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_home = (tmp_path / "user").resolve()
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    proj = fake_home / "projects" / "web-app"
    slug = AgentPaths._slugify_path(proj)
    assert slug.startswith("home-projects-web-app")


def test_project_session_dir_deterministic_and_unique(tmp_path: Path) -> None:
    paths = AgentPaths(home=tmp_path / "agent_home")
    proj_a = tmp_path / "workspace_a"
    proj_b = tmp_path / "workspace_b"
    proj_a.mkdir()
    proj_b.mkdir()

    dir_a1 = paths.project_session_dir(proj_a)
    dir_a2 = paths.project_session_dir(proj_a)
    dir_b = paths.project_session_dir(proj_b)

    assert dir_a1 == dir_a2
    assert dir_a1 != dir_b
    assert dir_a1.parent == paths.sessions_dir
    assert dir_a1.exists()


def test_default_session_path(tmp_path: Path) -> None:
    paths = AgentPaths(home=tmp_path / "agent_home")
    proj = tmp_path / "my_project"
    proj.mkdir()
    session_file = paths.default_session_path(proj)
    assert session_file.name == "default.jsonl"
    assert session_file.parent == paths.project_session_dir(proj)


def test_project_local_paths(tmp_path: Path) -> None:
    paths = AgentPaths(home=tmp_path / "agent_home")
    cwd = tmp_path / "workspace"
    assert paths.project_agent_dir(cwd) == cwd / ".my-pi-agent"
    assert paths.project_settings_path(cwd) == cwd / ".my-pi-agent" / "settings.json"
    assert paths.project_skills_dir(cwd) == cwd / ".my-pi-agent" / "skills"
    assert paths.project_agents_skills_dir(cwd) == cwd / ".agents" / "skills"


def test_ensure_directories(tmp_path: Path) -> None:
    paths = AgentPaths(home=tmp_path / "agent_home")
    paths.ensure_directories()
    assert paths.home.exists()
    assert paths.sessions_dir.exists()
    assert paths.skills_dir.exists()
    assert paths.prompts_dir.exists()
    assert paths.themes_dir.exists()
    assert paths.extensions_dir.exists()
    assert paths.logs_dir.exists()


def test_agent_paths_frozen_immutable(tmp_path: Path) -> None:
    paths = AgentPaths(home=tmp_path / "agent_home")
    with pytest.raises(FrozenInstanceError):
        paths.home = tmp_path / "other"  # type: ignore[misc]


def test_project_logs_dir_and_session_log_paths(tmp_path: Path) -> None:
    paths: AgentPaths = AgentPaths(home=tmp_path / "agent_home")
    proj = tmp_path / "my_project"
    proj.mkdir()

    logs_dir = paths.project_logs_dir(proj)
    assert logs_dir.parent == paths.logs_dir
    assert logs_dir.exists()

    session_id = "01a0ce3f-59e4-72b5-ad5c-231e9d2eca91"
    log_file = paths.session_log_path(proj, session_id)
    events_file = paths.session_events_path(proj, session_id)

    assert log_file == logs_dir / f"{session_id}.debug.log"
    assert events_file == logs_dir / f"{session_id}.events.jsonl"

