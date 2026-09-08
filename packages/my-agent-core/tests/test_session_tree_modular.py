"""Tests for modular session entries and pure in-memory DAG tree algorithms."""

import time

import pytest
from my_agent_core.session.entries import (
    BaseSessionEntry,
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionEntry,
    SessionInfoEntry,
    ThinkingLevelChangeEntry,
)
from my_agent_core.session.tree import (
    SessionTreeError,
    entries_by_id,
    lowest_common_ancestor,
    path_to_entry,
)
from my_agent_llm.models import Message
from pydantic import TypeAdapter, ValidationError

# ============================================================================
# 1. 9 种 SessionEntry 多态判别实体测试
# ============================================================================


def test_base_session_entry_defaults_and_forbid_extra() -> None:
    """BaseSessionEntry 默认生成 id 和 timestamp，且 extra='forbid' 禁止未知字段。"""
    entry = BaseSessionEntry()
    assert isinstance(entry.id, str) and len(entry.id) > 0
    assert entry.parent_id is None
    assert isinstance(entry.timestamp, float)
    assert entry.timestamp > 0

    # 支持驼峰 parentId 反序列化
    entry_camel = BaseSessionEntry.model_validate({"parentId": "p1", "timestamp": 123.4})
    assert entry_camel.parent_id == "p1"
    assert entry_camel.timestamp == 123.4

    # 禁止未知字段
    with pytest.raises(ValidationError):
        BaseSessionEntry.model_validate({"extra_unknown_field": "disallowed"})


def test_all_9_entries_instantiation_and_types() -> None:
    """验证 9 种多态实体各自的字段构造、默认值与类型判别标记。"""
    now = time.time()

    # 1. SessionInfoEntry
    info = SessionInfoEntry(cwd="/app", title="Main Session", created_at=now)
    assert info.type in ("session_info", "sessionInfo")
    assert info.cwd == "/app"
    assert info.title == "Main Session"
    assert info.created_at == now

    # 2. MessageEntry
    msg_obj = Message(role="user", content="Hello agent")
    msg_entry = MessageEntry(parent_id=info.id, message=msg_obj)
    assert msg_entry.type == "message"
    assert msg_entry.message.role == "user"
    assert msg_entry.message.content == "Hello agent"

    # 3. ModelChangeEntry
    model_entry = ModelChangeEntry(parent_id=msg_entry.id, model="gpt-4o", provider="openai")
    assert model_entry.type in ("model_change", "modelChange")
    assert model_entry.model == "gpt-4o"
    assert model_entry.provider == "openai"

    # 4. ThinkingLevelChangeEntry
    think_entry = ThinkingLevelChangeEntry(parent_id=model_entry.id, thinking_level="high")
    assert think_entry.type in ("thinking_level_change", "thinkingLevelChange")
    assert think_entry.thinking_level == "high"

    # 5. CompactionEntry
    compact_entry = CompactionEntry(
        parent_id=think_entry.id,
        summary="Previous context summary",
        replaces_entry_ids=[msg_entry.id],
    )
    assert compact_entry.type == "compaction"
    assert compact_entry.summary == "Previous context summary"
    assert compact_entry.replaces_entry_ids == [msg_entry.id]

    # 6. BranchSummaryEntry
    branch_entry = BranchSummaryEntry(
        parent_id=compact_entry.id,
        summary="Branch A completed exploration",
        details={"status": "explored"},
    )
    assert branch_entry.type in ("branch_summary", "branchSummary")
    assert branch_entry.summary == "Branch A completed exploration"
    assert branch_entry.details == {"status": "explored"}

    # 7. LabelEntry
    label_entry = LabelEntry(parent_id=branch_entry.id, label="checkpoint-1", target_id=branch_entry.id)
    assert label_entry.type == "label"
    assert label_entry.label == "checkpoint-1"
    assert label_entry.target_id == branch_entry.id

    # 8. LeafEntry
    leaf_entry = LeafEntry(parent_id=label_entry.id, leaf_id=label_entry.id)
    assert leaf_entry.type == "leaf"
    assert leaf_entry.leaf_id == label_entry.id

    # 9. CustomEntry
    custom_entry = CustomEntry(parent_id=leaf_entry.id, namespace="telemetry", data={"tokens": 100})
    assert custom_entry.type == "custom"
    assert custom_entry.namespace == "telemetry"
    assert custom_entry.data == {"tokens": 100}


def test_discriminated_union_serialization_and_deserialization() -> None:
    """测试通过 Pydantic v2 TypeAdapter 对 SessionEntry 判别联合体进行序列化与多态反序列化。"""
    adapter = TypeAdapter(SessionEntry)

    raw_items = [
        {"type": "session_info", "id": "e0", "title": "Init", "cwd": "/root"},
        {"type": "message", "id": "e1", "parentId": "e0", "message": {"role": "user", "content": "hi"}},
        {"type": "model_change", "id": "e2", "parentId": "e1", "model": "claude-3-5-sonnet", "provider": "anthropic"},
        {"type": "thinking_level_change", "id": "e3", "parentId": "e2", "thinking_level": "medium"},
        {"type": "compaction", "id": "e4", "parentId": "e3", "summary": "ctx", "replaces_entry_ids": ["e1"]},
        {"type": "branch_summary", "id": "e5", "parentId": "e4", "summary": "br summary"},
        {"type": "label", "id": "e6", "parentId": "e5", "label": "v1.0"},
        {"type": "leaf", "id": "e7", "parentId": "e6", "leaf_id": "e6"},
        {"type": "custom", "id": "e8", "parentId": "e7", "namespace": "plugin_x", "data": {"key": "val"}},
    ]

    parsed_entries: list[SessionEntry] = [adapter.validate_python(item) for item in raw_items]

    assert isinstance(parsed_entries[0], SessionInfoEntry)
    assert isinstance(parsed_entries[1], MessageEntry)
    assert isinstance(parsed_entries[2], ModelChangeEntry)
    assert isinstance(parsed_entries[3], ThinkingLevelChangeEntry)
    assert isinstance(parsed_entries[4], CompactionEntry)
    assert isinstance(parsed_entries[5], BranchSummaryEntry)
    assert isinstance(parsed_entries[6], LabelEntry)
    assert isinstance(parsed_entries[7], LeafEntry)
    assert isinstance(parsed_entries[8], CustomEntry)

    # 验证驼峰与蛇形互转支持
    dumped_camel = parsed_entries[1].model_dump(by_alias=True)
    assert dumped_camel["parentId"] == "e0"

    dumped_snake = parsed_entries[1].model_dump(by_alias=False)
    assert dumped_snake["parent_id"] == "e0"


def test_discriminated_union_invalid_type_raises() -> None:
    """非法 discriminator 类型触发 ValidationError。"""
    adapter = TypeAdapter(SessionEntry)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "unknown_entry_type", "id": "bad"})


def test_entries_extra_fields_forbidden() -> None:
    """各具体 SessionEntry 均继承 extra='forbid' 特性。"""
    adapter = TypeAdapter(SessionEntry)
    with pytest.raises(ValidationError):
        adapter.validate_python({
            "type": "model_change",
            "id": "m1",
            "model": "gpt-4o",
            "unsupported_extra_key": "fail",
        })


# ============================================================================
# 2. 纯内存 DAG 算法 entries_by_id 测试
# ============================================================================


def test_entries_by_id_normal() -> None:
    """entries_by_id 将条目列表转换为 ID 索引字典。"""
    e1 = SessionInfoEntry(id="info1")
    e2 = MessageEntry(id="msg1", parent_id="info1", message=Message(role="user", content="hello"))
    by_id = entries_by_id([e1, e2])
    assert by_id == {"info1": e1, "msg1": e2}


def test_entries_by_id_duplicate_id_raises_error() -> None:
    """遇到重复 ID 时必须抛出 SessionTreeError，并继承自 ValueError。"""
    e1 = SessionInfoEntry(id="dup_id", title="first")
    e2 = MessageEntry(id="dup_id", message=Message(role="user", content="second"))
    with pytest.raises(SessionTreeError, match="Duplicate entry id: dup_id") as exc_info:
        entries_by_id([e1, e2])
    assert isinstance(exc_info.value, ValueError)


# ============================================================================
# 3. 纯内存 DAG 算法 path_to_entry 测试
# ============================================================================


def test_path_to_entry_linear_chain() -> None:
    """单链线性溯源返回根到叶的完整路径。"""
    e0 = SessionInfoEntry(id="0", parent_id=None)
    e1 = MessageEntry(id="1", parent_id="0", message=Message(role="user", content="q1"))
    e2 = MessageEntry(id="2", parent_id="1", message=Message(role="assistant", content="a1"))
    e3 = LeafEntry(id="3", parent_id="2", leaf_id="2")

    path = path_to_entry([e0, e1, e2, e3], "3")
    assert [e.id for e in path] == ["0", "1", "2", "3"]


def test_path_to_entry_branching() -> None:
    """在分叉树中正确提取指定分支的根到叶路径。"""
    # 树形结构:
    #      e0
    #     /  \
    #    e1   e2
    #    |    |
    #    e3   e4
    e0 = SessionInfoEntry(id="e0")
    e1 = MessageEntry(id="e1", parent_id="e0", message=Message(role="user", content="b1"))
    e3 = MessageEntry(id="e3", parent_id="e1", message=Message(role="assistant", content="b1_ans"))
    e2 = MessageEntry(id="e2", parent_id="e0", message=Message(role="user", content="b2"))
    e4 = MessageEntry(id="e4", parent_id="e2", message=Message(role="assistant", content="b2_ans"))

    path_b1 = path_to_entry([e0, e1, e2, e3, e4], "e3")
    assert [e.id for e in path_b1] == ["e0", "e1", "e3"]

    path_b2 = path_to_entry([e0, e1, e2, e3, e4], "e4")
    assert [e.id for e in path_b2] == ["e0", "e2", "e4"]


def test_path_to_entry_missing_leaf_id() -> None:
    """请求不存在的叶节点 ID 抛出 SessionTreeError。"""
    e0 = SessionInfoEntry(id="e0")
    with pytest.raises(SessionTreeError, match="not found"):
        path_to_entry([e0], "non_existent")


def test_path_to_entry_missing_parent_id() -> None:
    """条目的父节点缺失抛出 SessionTreeError。"""
    e1 = MessageEntry(id="e1", parent_id="missing_parent", message=Message(role="user", content="hi"))
    with pytest.raises(SessionTreeError, match="Missing parent entry.*missing_parent"):
        path_to_entry([e1], "e1")


def test_path_to_entry_self_cycle_detected() -> None:
    """节点父指针指向自身探测到环路抛出 SessionTreeError(Cycle detected)。"""
    e0 = SessionInfoEntry(id="self_loop", parent_id="self_loop")
    with pytest.raises(SessionTreeError, match="Cycle detected"):
        path_to_entry([e0], "self_loop")


def test_path_to_entry_multi_node_cycle_detected() -> None:
    """多节点循环死锁探测到环路抛出 SessionTreeError(Cycle detected)。"""
    # a -> b -> c -> a
    ea = MessageEntry(id="a", parent_id="c", message=Message(role="user", content="a"))
    eb = MessageEntry(id="b", parent_id="a", message=Message(role="assistant", content="b"))
    ec = MessageEntry(id="c", parent_id="b", message=Message(role="user", content="c"))

    with pytest.raises(SessionTreeError, match="Cycle detected"):
        path_to_entry([ea, eb, ec], "c")


# ============================================================================
# 4. 纯内存 DAG 算法 lowest_common_ancestor 测试
# ============================================================================


def test_lowest_common_ancestor() -> None:
    """计算分叉树中两个节点的最近公共祖先 (LCA)。"""
    #      root
    #     /    \
    #    b1     b2
    #    |      |
    #   b1_leaf b2_leaf
    root = SessionInfoEntry(id="root")
    b1 = MessageEntry(id="b1", parent_id="root", message=Message(role="user", content="b1"))
    b1_leaf = MessageEntry(id="b1_leaf", parent_id="b1", message=Message(role="assistant", content="b1_leaf"))
    b2 = MessageEntry(id="b2", parent_id="root", message=Message(role="user", content="b2"))
    b2_leaf = MessageEntry(id="b2_leaf", parent_id="b2", message=Message(role="assistant", content="b2_leaf"))

    entries = [root, b1, b1_leaf, b2, b2_leaf]
    assert lowest_common_ancestor(entries, "b1_leaf", "b2_leaf") == "root"
    assert lowest_common_ancestor(entries, "b1_leaf", "b1") == "b1"
    assert lowest_common_ancestor(entries, "b1_leaf", "root") == "root"

