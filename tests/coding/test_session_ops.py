from __future__ import annotations

from pathlib import Path
import pytest

from my_agent_core.session import Session
from my_coding_agent.paths import AgentPaths
from my_coding_agent.session_ops import (
    build_tree_nodes,
    compute_session_stats,
    compute_session_usage,
    list_project_sessions,
    resolve_session_file,
)


def test_compute_session_usage_empty(tmp_path: Path) -> None:
    session = Session(path=tmp_path / "empty.jsonl")
    usage = compute_session_usage(session, "gpt-4o")
    assert usage["input"] == 0
    assert usage["output"] == 0
    assert usage["total"] == 0
    assert usage["cost"] == 0.0


def test_build_tree_nodes_and_stats(tmp_path: Path) -> None:
    session = Session(path=tmp_path / "test.jsonl", cwd=str(tmp_path))
    session.add_message("user", "Hello world")
    session.add_message(
        "assistant",
        "Hi there!",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )

    nodes, active_leaf, root = build_tree_nodes(session)
    assert len(nodes) >= 2
    assert active_leaf is not None
    assert root is not None

    stats = compute_session_stats(session, default_model="gpt-4o", default_provider="openai")
    assert stats["totalMessages"] == 2
    assert stats["userMessages"] == 1
    assert stats["assistantMessages"] == 1
    assert stats["tokens"]["input"] == 100
    assert stats["tokens"]["output"] == 50


def test_list_and_resolve_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    paths = AgentPaths()

    work = tmp_path / "work"
    work.mkdir()
    sess_dir = paths.project_session_dir(work)
    sess_dir.mkdir(parents=True, exist_ok=True)

    session = Session(path=sess_dir / "sess-1.jsonl", cwd=str(work))
    session.id = "sess-1"
    session.add_message("user", "first message")
    session.save()

    sessions = list_project_sessions(paths, work, all_projects=False)
    assert len(sessions) == 1
    assert sessions[0]["id"] == "sess-1"
    assert sessions[0]["first_message"] == "first message"

    resolved, matches = resolve_session_file("sess-1", paths, work)
    assert resolved is not None
    assert resolved.name == "sess-1.jsonl"
