"""SessionTree 树结构测试（会话设计文档 §8 #1–#3）。"""
import json
from pathlib import Path

from my_agent_core.session import Session, SessionTree
from my_agent_llm import Message


def test_tree_first_entry_is_root():
    """首个 entry 成为根，current 指向它（#1）。"""
    tree = SessionTree()
    e = tree.add_entry("user", "hi")
    assert tree.root_id == e.id
    assert tree.current_id == e.id
    assert e.parent_id is None
    assert e.role == "user"
    assert e.content == "hi"


def test_tree_path_root_to_current():
    """多 entry 后 get_current_path = 根→current 完整路径（#2）。"""
    tree = SessionTree()
    tree.add_entry("user", "q1")
    tree.add_entry("assistant", "a1")
    tree.add_entry("user", "q2")
    path = tree.get_current_path()
    assert [e.content for e in path] == ["q1", "a1", "q2"]
    assert path[0].id == tree.root_id
    assert path[-1].id == tree.current_id


def test_tree_rewind_keeps_old_branch():
    """rewind 移动 current 指针，旧分支 entry 仍在树里；rewind 后长新枝 parent 正确（#3）。"""
    tree = SessionTree()
    tree.add_entry("user", "q1")
    a = tree.add_entry("assistant", "a1")
    tree.add_entry("user", "q2")
    tree.rewind(a.id)
    assert tree.current_id == a.id
    assert len(tree.entries) == 3  # 旧分支保留
    assert [e.content for e in tree.get_current_path()] == ["q1", "a1"]
    # rewind 后继续 → 在 a1 下长新枝
    b = tree.add_entry("user", "q2-prime")
    assert b.parent_id == a.id
    assert [e.content for e in tree.get_current_path()] == ["q1", "a1", "q2-prime"]
    assert "q2" in [e.content for e in tree.entries.values()]  # 旧枝完整保留


def test_tree_rewind_missing_entry_raises():
    """rewind 到不存在的 entry 抛 ValueError（设计文档 §7）。"""
    tree = SessionTree()
    tree.add_entry("user", "hi")
    try:
        tree.rewind("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_save_load_round_trip(tmp_path):
    """加几条消息 → save → load → 树全等（entries 数、current/root）（#4）。"""
    session = Session(path=tmp_path / "s.jsonl", system_prompt="sys")
    session.add_message("user", "q1")
    session.add_message("assistant", "a1")
    loaded = Session.load(session.path)
    assert len(loaded.tree.entries) == 3
    assert loaded.tree.root_id == session.tree.root_id
    assert loaded.tree.current_id == session.tree.current_id
    assert [e.content for e in loaded.tree.get_current_path()] == ["sys", "q1", "a1"]


def test_messages_round_trip_with_metadata(tmp_path):
    """get_current_path_messages → list[Message]，tool_calls/tool_call_id 在 metadata（#5）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
    session = Session(path=tmp_path / "s.jsonl", system_prompt="sys")
    session.add_message("user", "q1")
    session.add_message("assistant", "", tool_calls=tc)
    session.add_message("tool", "42", tool_call_id="1")
    msgs = session.get_current_path_messages()
    assert [m.role for m in msgs] == ["system", "user", "assistant", "tool"]
    assert msgs[2].metadata["tool_calls"] == tc
    assert msgs[3].metadata["tool_call_id"] == "1"
    # Message 往返：model_dump → model_validate 一致
    assert msgs[0] == Message.model_validate(msgs[0].model_dump())


def test_atomic_write_tmp_remnant_does_not_break(tmp_path):
    """save 后文件完整；目录里残留损坏 tmp 文件不影响加载（#6）。"""
    session = Session(path=tmp_path / "s.jsonl", system_prompt="sys")
    session.add_message("user", "q1")
    (tmp_path / ".s.jsonl.abc.tmp").write_text("garbage", encoding="utf-8")
    loaded = Session.load(session.path)
    assert [e.content for e in loaded.tree.get_current_path()] == ["sys", "q1"]


def test_atomic_write_failure_keeps_snapshot(tmp_path, monkeypatch):
    """写中断（os.replace 抛错）→ 上次快照不被破坏（#6）。"""
    session = Session(path=tmp_path / "s.jsonl", system_prompt="sys")
    session.add_message("user", "q1")
    snapshot = session.path.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("my_agent_core.session.os.replace", boom)
    try:
        session.add_message("user", "q2")
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")
    assert session.path.read_text(encoding="utf-8") == snapshot  # 快照未变


def test_load_tolerates_torn_last_line(tmp_path):
    """尾行撕裂（不完整 JSON）→ 丢弃该行，其余正常加载（设计文档 §7）。"""
    session = Session(path=tmp_path / "s.jsonl", system_prompt="sys")
    session.add_message("user", "q1")
    session.add_message("assistant", "a1")
    with open(session.path, "a", encoding="utf-8") as f:
        f.write('{"id":"zz","parent_id"')  # 撕裂尾行
    loaded = Session.load(session.path)
    assert [e.content for e in loaded.tree.get_current_path()] == ["sys", "q1", "a1"]