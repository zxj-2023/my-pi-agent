from __future__ import annotations

from pathlib import Path
import pytest

from my_agent_core.session import Session
from my_coding_agent.paths import AgentPaths
from my_coding_agent.session_ops import (
    branch_session_tree,
    build_tree_nodes,
    clone_session_tree,
    compute_session_stats,
    compute_session_usage,
    fork_session_tree,
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


def test_fork_and_clone_session_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    paths = AgentPaths()
    work = tmp_path / "work"
    work.mkdir()

    session = Session(path=tmp_path / "source.jsonl", cwd=str(work))
    m1 = session.add_message("user", "first message")
    session.add_message("assistant", "first response")
    session.save()

    # Test fork
    forked_session, prompt_text, forked_file = fork_session_tree(session, m1.id, paths, work)
    assert forked_session.id != session.id
    assert forked_session.metadata["forked_from_entry_id"] == m1.id
    assert prompt_text == "first message"
    assert forked_file.is_file()

    # Test clone
    cloned_session, clone_title, cloned_file = clone_session_tree(session, paths, work)
    assert cloned_session.id != session.id
    assert "Clone" in clone_title
    assert cloned_file.is_file()
    assert len(cloned_session.get_full_history_messages()) == 2


@pytest.mark.anyio
async def test_branch_session_tree(tmp_path: Path) -> None:
    session = Session(path=tmp_path / "branch_test.jsonl", cwd=str(tmp_path))
    m1 = session.add_message("user", "Hello")
    m2 = session.add_message("assistant", "World")
    session.save()

    # Branch back to m1 (user message -> new leaf is parent of m1, i.e. None / root)
    new_leaf, editor_text, summary, messages = await branch_session_tree(
        session=session,
        target_id=m1.id,
        summarize=False,
    )
    assert new_leaf is None
    assert editor_text == "Hello"
    assert len(messages) == 0

    # Branch back to m2 (assistant message -> new leaf is m2)
    new_leaf2, editor_text2, summary2, messages2 = await branch_session_tree(
        session=session,
        target_id=m2.id,
        summarize=False,
    )
    assert new_leaf2 == m2.id
    assert editor_text2 == ""
    assert len(messages2) == 2
