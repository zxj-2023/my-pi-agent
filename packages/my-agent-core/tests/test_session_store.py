"""SessionStore 会话仓库测试（会话设计文档 §8 #11）。"""
import json

import pytest

from my_agent_core.session_store import SessionMeta, SessionStore


def test_store_create_list_open_delete(tmp_path):
    """create/list（倒序）/open 全 id/open 前缀/delete；连续 create 不同 id（#11）。"""
    store = SessionStore(tmp_path)
    s1 = store.create()
    s2 = store.create()
    assert s1.id != s2.id
    metas = store.list()
    assert [m.id for m in metas] == [s2.id, s1.id]  # 倒序（新→旧）
    assert store.open(s1.id).id == s1.id            # 全 id
    assert store.open(s1.id[:20]).id == s1.id       # 唯一前缀（时间戳段相同，前缀须含 hex）
    store.delete(s1.id)
    assert [m.id for m in store.list()] == [s2.id]
    with pytest.raises(ValueError):
        store.open("nope")


def test_store_create_writes_header_only(tmp_path):
    """create 后文件存在且只有 header 行（纯对话，不含 system）（§5）。"""
    store = SessionStore(tmp_path)
    s = store.create()
    lines = s.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    header = json.loads(lines[0])
    assert header["id"] == s.id
    assert isinstance(header["created_at"], str)
    assert "type" not in header and "version" not in header  # type/version 已删


def test_store_open_ambiguous_prefix_raises(tmp_path):
    """前缀匹配到多个 → ValueError（列候选）（§7）。"""
    store = SessionStore(tmp_path)
    store.create()
    # 手工造两个同前缀文件
    for suffix in ("abc11111", "abc22222"):
        (tmp_path / f"{suffix}.jsonl").write_text(
            json.dumps(
                {"type": "session", "version": 1, "id": suffix,
                 "created_at": "2026-08-06T00:00:00", "cwd": ".",
                 "current_id": None, "root_id": None}
            )
            + "\n",
            encoding="utf-8",
        )
    with pytest.raises(ValueError) as excinfo:
        store.open("abc")
    assert "abc11111" in str(excinfo.value)
    assert "abc22222" in str(excinfo.value)


def test_store_list_skips_corrupt_files(tmp_path):
    """损坏的 .jsonl 文件被跳过，不放倒 list（SessionInfo 宽容）。"""
    store = SessionStore(tmp_path)
    store.create()
    (tmp_path / "corrupt.jsonl").write_text("not json\n", encoding="utf-8")
    metas = store.list()
    assert all(m.id != "corrupt" for m in metas)


def test_store_fork_copies_path_to_new_session(tmp_path):
    """fork 复制根→entry 路径为新会话；新会话 id 不同、树 = 复制路径（#13）。"""
    store = SessionStore(tmp_path)
    session = store.create()
    session.add_message("user", "q1")
    a = session.add_message("assistant", "a1")
    session.add_message("user", "q2")  # current 移到 q2（fork 点 a1 之前的旧枝）
    forked = store.fork(session.id, a.id)
    assert forked.id != session.id
    assert forked.cwd == session.cwd
    assert [e.content for e in forked.tree.get_current_path()] == ["q1", "a1"]


def test_store_fork_sessions_evolve_independently(tmp_path):
    """fork 后新旧会话独立演化（互不影响）（#13）。"""
    store = SessionStore(tmp_path)
    session = store.create()
    session.add_message("user", "q1")
    a = session.add_message("assistant", "a1")
    forked = store.fork(session.id, a.id)
    # 旧会话继续
    session.add_message("user", "q2")
    # 新会话从文件恢复后继续
    re_forked = store.open(forked.id)
    re_forked.add_message("user", "新枝")
    assert [e.content for e in session.tree.get_current_path()] == ["q1", "a1", "q2"]
    assert [e.content for e in re_forked.tree.get_current_path()] == ["q1", "a1", "新枝"]


def test_store_fork_missing_entry_raises(tmp_path):
    """fork 到不存在的 entry 抛 ValueError（§7）。"""
    store = SessionStore(tmp_path)
    session = store.create()
    with pytest.raises(ValueError):
        store.fork(session.id, "nope")


def test_store_workspace_isolation(tmp_path):
    """两个 workspace 各自 create → list 互不可见；文件在 <workspace>/.my_agent_core/sessions/ 下（#14）。"""
    store_a = SessionStore(workspace=tmp_path / "proj-a")
    store_b = SessionStore(workspace=tmp_path / "proj-b")
    sa = store_a.create()
    sb = store_b.create()
    assert [m.id for m in store_a.list()] == [sa.id]
    assert [m.id for m in store_b.list()] == [sb.id]  # 互不可见
    # 各自目录独立
    assert (tmp_path / "proj-a" / ".my_agent_core" / "sessions" / f"{sa.id}.jsonl").exists()
    assert (tmp_path / "proj-b" / ".my_agent_core" / "sessions" / f"{sb.id}.jsonl").exists()
    # Session.cwd = workspace
    assert sa.cwd == str(tmp_path / "proj-a")
    assert sb.cwd == str(tmp_path / "proj-b")


def test_store_absolute_root_ignores_workspace(tmp_path):
    """root 为绝对路径时直接用（不做 workspace/root 拼接）——现有测试兼容。"""
    store = SessionStore(root=tmp_path, workspace=tmp_path / "elsewhere")
    s = store.create()
    assert s.path.parent == tmp_path
    assert (tmp_path / f"{s.id}.jsonl").exists()