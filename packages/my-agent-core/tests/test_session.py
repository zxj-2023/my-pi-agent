"""SessionTree 树结构测试（会话设计文档 §8 #1–#3）。"""
from my_agent_core.session import SessionTree


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