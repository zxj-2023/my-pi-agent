"""Unit tests for pure in-memory session state projection (memory.py)
and append-only session storage protocol / InMemorySessionStorage (storage.py).
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest
from my_agent_llm.models import Message

from my_agent_core.session.entries import (
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionInfoEntry,
    ThinkingLevelChangeEntry,
)
from my_agent_core.session.memory import SessionState
from my_agent_core.session.storage import InMemorySessionStorage, SessionStorage
from my_agent_core.session.tree import SessionTreeError

# ============================================================================
# 1. SessionState 基础与不可变性 (Immutability) 测试
# ============================================================================


def test_session_state_defaults_and_frozen() -> None:
    """SessionState 具备默认字段，且为 frozen dataclass 禁止就地修改。"""
    state = SessionState()
    assert state.messages == ()
    assert state.model is None
    assert state.provider is None
    assert state.thinking_level is None
    assert state.label is None
    assert state.active_leaf_id is None

    # 不可变性测试：修改字段抛出 FrozenInstanceError
    with pytest.raises((FrozenInstanceError, AttributeError)):
        state.model = "new-model"  # type: ignore[misc]

    with pytest.raises((FrozenInstanceError, AttributeError)):
        state.messages = (Message(role="user", content="hi"),)  # type: ignore[misc]


def test_session_state_from_empty_entries() -> None:
    """对空条目序列执行折叠，返回默认 SessionState。"""
    state = SessionState.from_entries([])
    assert state.messages == ()
    assert state.model is None
    assert state.provider is None
    assert state.thinking_level is None
    assert state.label is None
    assert state.active_leaf_id is None


# ============================================================================
# 2. 状态折叠：SessionInfo, Message, ModelChange, ThinkingLevel, Label
# ============================================================================


def test_fold_sequential_lifecycle_entries() -> None:
    """顺次折叠 SessionInfoEntry、MessageEntry、ModelChangeEntry、ThinkingLevelChangeEntry、LabelEntry。"""
    e0 = SessionInfoEntry(id="info", cwd="/repo", title="Main Session")
    e1 = MessageEntry(
        id="m1",
        parent_id="info",
        message=Message(role="user", content="Hello agent"),
    )
    e2 = MessageEntry(
        id="m2",
        parent_id="m1",
        message=Message(role="assistant", content="Hello user"),
    )
    e3 = ModelChangeEntry(
        id="mc1",
        parent_id="m2",
        model="claude-3-7-sonnet",
        provider="anthropic",
    )
    e4 = ThinkingLevelChangeEntry(
        id="tc1",
        parent_id="mc1",
        thinking_level="high",
    )
    e5 = LabelEntry(
        id="lbl1",
        parent_id="tc1",
        label="checkpoint-v1",
    )

    state = SessionState.from_entries([e0, e1, e2, e3, e4, e5])

    assert len(state.messages) == 2
    assert state.messages[0] == e1.message
    assert state.messages[1] == e2.message
    assert state.model == "claude-3-7-sonnet"
    assert state.provider == "anthropic"
    assert state.thinking_level == "high"
    assert state.label == "checkpoint-v1"
    assert state.active_leaf_id == "lbl1"


def test_fold_model_change_preserves_provider_when_unspecified() -> None:
    """当后续 ModelChangeEntry 未指定 provider 时，保留先前已设定的 provider。"""
    e0 = SessionInfoEntry(id="info")
    e1 = ModelChangeEntry(
        id="mc1",
        parent_id="info",
        model="gpt-4o",
        provider="openai",
    )
    e2 = ModelChangeEntry(
        id="mc2",
        parent_id="mc1",
        model="gpt-4o-mini",
        provider=None,
    )

    state = SessionState.from_entries([e0, e1, e2])
    assert state.model == "gpt-4o-mini"
    assert state.provider == "openai"


def test_fold_ignores_non_state_entries_gracefully() -> None:
    """CustomEntry 和 BranchSummaryEntry 不污染对话消息与状态字段，但能正常作为路径节点折叠。"""
    e0 = SessionInfoEntry(id="info")
    e1 = MessageEntry(
        id="m1",
        parent_id="info",
        message=Message(role="user", content="ping"),
    )
    e2 = CustomEntry(
        id="c1",
        parent_id="m1",
        namespace="telemetry",
        data={"metric": 42},
    )
    e3 = BranchSummaryEntry(
        id="bs1",
        parent_id="c1",
        summary="Explored branch A",
        details={"tokens": 100},
    )

    state = SessionState.from_entries([e0, e1, e2, e3])
    assert len(state.messages) == 1
    assert state.messages[0].content == "ping"
    assert state.active_leaf_id == "bs1"


# ============================================================================
# 3. 上下文压缩条目 (CompactionEntry) 自动覆盖折叠测试
# ============================================================================


def test_fold_compaction_replaces_early_messages() -> None:
    """遇到 CompactionEntry 时，自动将 replaces_entry_ids 范围内的历史消息折叠为一条 UserMessage 摘要。"""
    e0 = SessionInfoEntry(id="info")
    m1 = MessageEntry(
        id="m1",
        parent_id="info",
        message=Message(role="user", content="Turn 1 question"),
    )
    m2 = MessageEntry(
        id="m2",
        parent_id="m1",
        message=Message(role="assistant", content="Turn 1 answer"),
    )
    m3 = MessageEntry(
        id="m3",
        parent_id="m2",
        message=Message(role="user", content="Turn 2 question"),
    )
    compaction = CompactionEntry(
        id="cmp1",
        parent_id="m3",
        summary="Turn 1 covered greetings and general inquiries.",
        replaces_entry_ids=["m1", "m2"],
    )
    m4 = MessageEntry(
        id="m4",
        parent_id="cmp1",
        message=Message(role="assistant", content="Turn 2 answer"),
    )

    state = SessionState.from_entries([e0, m1, m2, m3, compaction, m4])

    assert len(state.messages) == 3
    # 消息 0: 折叠后的摘要消息
    assert state.messages[0].role == "user"
    assert "Previous conversation summary:" in state.messages[0].content
    assert "Turn 1 covered greetings" in state.messages[0].content
    # 消息 1: 未被压缩的 m3
    assert state.messages[1] == m3.message
    # 消息 2: 压缩之后的新消息 m4
    assert state.messages[2] == m4.message
    assert state.active_leaf_id == "m4"


def test_fold_cascading_compactions() -> None:
    """多次连续上下文压缩：第二次 CompactionEntry 可进一步替换前一次的 Compaction 与后续消息。"""
    e0 = SessionInfoEntry(id="info")
    m1 = MessageEntry(
        id="m1", parent_id="info", message=Message(role="user", content="q1")
    )
    m2 = MessageEntry(
        id="m2", parent_id="m1", message=Message(role="assistant", content="a1")
    )
    c1 = CompactionEntry(
        id="c1",
        parent_id="m2",
        summary="Summary 1",
        replaces_entry_ids=["m1", "m2"],
    )
    m3 = MessageEntry(
        id="m3", parent_id="c1", message=Message(role="user", content="q2")
    )
    m4 = MessageEntry(
        id="m4", parent_id="m3", message=Message(role="assistant", content="a2")
    )
    c2 = CompactionEntry(
        id="c2",
        parent_id="m4",
        summary="Summary 2 including q2",
        replaces_entry_ids=["c1", "m3"],
    )
    m5 = MessageEntry(
        id="m5", parent_id="c2", message=Message(role="user", content="q3")
    )

    state = SessionState.from_entries([e0, m1, m2, c1, m3, m4, c2, m5])

    assert len(state.messages) == 3
    assert state.messages[0].role == "user"
    assert "Summary 2 including q2" in state.messages[0].content
    assert state.messages[1] == m4.message
    assert state.messages[2] == m5.message
    assert state.active_leaf_id == "m5"


def test_fold_compaction_no_duplicate_prefix() -> None:
    """若 CompactionEntry.summary 自身已经包含摘要前缀，折叠时不再重复拼接。"""
    e0 = SessionInfoEntry(id="info")
    m1 = MessageEntry(
        id="m1", parent_id="info", message=Message(role="user", content="q1")
    )
    c1 = CompactionEntry(
        id="c1",
        parent_id="m1",
        summary="Previous conversation summary:\nAlready prefixed",
        replaces_entry_ids=["m1"],
    )

    state = SessionState.from_entries([e0, m1, c1])
    assert len(state.messages) == 1
    assert (
        state.messages[0].content == "Previous conversation summary:\nAlready prefixed"
    )


def test_fold_compaction_replaces_middle_messages() -> None:
    """压缩位于中间位置的消息时，保留前缀消息与后续消息。"""
    e0 = SessionInfoEntry(id="info")
    m1 = MessageEntry(
        id="m1", parent_id="info", message=Message(role="user", content="msg 1")
    )
    m2 = MessageEntry(
        id="m2", parent_id="m1", message=Message(role="assistant", content="msg 2")
    )
    m3 = MessageEntry(
        id="m3", parent_id="m2", message=Message(role="user", content="msg 3")
    )
    c1 = CompactionEntry(
        id="c1",
        parent_id="m3",
        summary="summary of msg 2",
        replaces_entry_ids=["m2"],
    )
    m4 = MessageEntry(
        id="m4", parent_id="c1", message=Message(role="assistant", content="msg 4")
    )

    state = SessionState.from_entries([e0, m1, m2, m3, c1, m4])
    assert len(state.messages) == 4
    assert state.messages[0] == m1.message
    assert "summary of msg 2" in state.messages[1].content
    assert state.messages[2] == m3.message
    assert state.messages[3] == m4.message


def test_fold_compaction_with_no_matching_ids_appends() -> None:
    """若 replaces_entry_ids 未命中任何现有消息，折叠时安全追加摘要。"""
    e0 = SessionInfoEntry(id="info")
    m1 = MessageEntry(
        id="m1", parent_id="info", message=Message(role="user", content="msg 1")
    )
    c1 = CompactionEntry(
        id="c1",
        parent_id="m1",
        summary="orphaned summary",
        replaces_entry_ids=["non_existent_id"],
    )

    state = SessionState.from_entries([e0, m1, c1])
    assert len(state.messages) == 2
    assert state.messages[0] == m1.message
    assert "orphaned summary" in state.messages[1].content


def test_fold_compaction_empty_replaces_appends() -> None:
    """replaces_entry_ids 为空列表时，直接追加摘要消息。"""
    e0 = SessionInfoEntry(id="info")
    m1 = MessageEntry(
        id="m1", parent_id="info", message=Message(role="user", content="msg 1")
    )
    c1 = CompactionEntry(
        id="c1",
        parent_id="m1",
        summary="appended summary",
        replaces_entry_ids=[],
    )

    state = SessionState.from_entries([e0, m1, c1])
    assert len(state.messages) == 2
    assert state.messages[0] == m1.message
    assert "appended summary" in state.messages[1].content


def test_fold_single_entry() -> None:
    """单条目（只有 SessionInfoEntry）折叠。"""
    e0 = SessionInfoEntry(id="info_only")
    state = SessionState.from_entries([e0])
    assert state.messages == ()
    assert state.active_leaf_id == "info_only"


# ============================================================================
# 4. 分支溯源与 LeafEntry / 指定 leaf_id 投影测试
# ============================================================================


def test_fold_with_explicit_leaf_id() -> None:
    """显式指定 leaf_id 时，仅沿根至指定节点的路径回溯折叠。"""
    # 树形分支:
    #       e0
    #      /  \
    #     m1   m2
    #     |    |
    #     m3   m4
    e0 = SessionInfoEntry(id="e0")
    m1 = MessageEntry(
        id="m1", parent_id="e0", message=Message(role="user", content="branch 1 q")
    )
    m3 = MessageEntry(
        id="m3", parent_id="m1", message=Message(role="assistant", content="branch 1 a")
    )
    m2 = MessageEntry(
        id="m2", parent_id="e0", message=Message(role="user", content="branch 2 q")
    )
    m4 = MessageEntry(
        id="m4", parent_id="m2", message=Message(role="assistant", content="branch 2 a")
    )

    all_entries = [e0, m1, m3, m2, m4]

    state_b1 = SessionState.from_entries(all_entries, leaf_id="m3")
    assert [m.content for m in state_b1.messages] == ["branch 1 q", "branch 1 a"]
    assert state_b1.active_leaf_id == "m3"

    state_b2 = SessionState.from_entries(all_entries, leaf_id="m4")
    assert [m.content for m in state_b2.messages] == ["branch 2 q", "branch 2 a"]
    assert state_b2.active_leaf_id == "m4"


def test_fold_auto_detects_last_leaf_entry() -> None:
    """当 leaf_id=None 时，自动采用序列中最后一个 LeafEntry 所指向的叶节点。"""
    e0 = SessionInfoEntry(id="e0")
    m1 = MessageEntry(
        id="m1", parent_id="e0", message=Message(role="user", content="b1")
    )
    m2 = MessageEntry(
        id="m2", parent_id="e0", message=Message(role="user", content="b2")
    )
    # 追加 LeafEntry 指回 m1
    leaf1 = LeafEntry(id="l1", parent_id="m2", leaf_id="m1")

    state = SessionState.from_entries([e0, m1, m2, leaf1])
    assert [m.content for m in state.messages] == ["b1"]
    assert state.active_leaf_id == "m1"

    # 再次追加 LeafEntry 切换至 m2
    leaf2 = LeafEntry(id="l2", parent_id="l1", leaf_id="m2")
    state2 = SessionState.from_entries([e0, m1, m2, leaf1, leaf2])
    assert [m.content for m in state2.messages] == ["b2"]
    assert state2.active_leaf_id == "m2"


def test_fold_raises_on_nonexistent_leaf_id() -> None:
    """指定不存在的 leaf_id 时抛出 SessionTreeError。"""
    e0 = SessionInfoEntry(id="e0")
    with pytest.raises(SessionTreeError):
        SessionState.from_entries([e0], leaf_id="not_exist")


# ============================================================================
# 5. SessionStorage 协议与 InMemorySessionStorage 纯内存存储测试
# ============================================================================


@pytest.mark.anyio
async def test_in_memory_storage_protocol_and_empty() -> None:
    """InMemorySessionStorage 遵循 SessionStorage 协议且初始读为空。"""
    storage = InMemorySessionStorage()
    assert isinstance(storage, SessionStorage)

    entries = await storage.read_all()
    assert entries == []


@pytest.mark.anyio
async def test_in_memory_storage_append_and_read() -> None:
    """InMemorySessionStorage 单项追加与批量追加契约。"""
    storage = InMemorySessionStorage()
    e0 = SessionInfoEntry(id="e0")
    m1 = MessageEntry(
        id="m1", parent_id="e0", message=Message(role="user", content="hi")
    )
    m2 = MessageEntry(
        id="m2", parent_id="m1", message=Message(role="assistant", content="there")
    )

    await storage.append(e0)
    entries = await storage.read_all()
    assert entries == [e0]

    await storage.append_batch([m1, m2])
    entries_after_batch = await storage.read_all()
    assert entries_after_batch == [e0, m1, m2]

    # 返回的列表是隔离浅拷贝，修改外部列表不污染内部存储
    entries_after_batch.clear()
    assert len(await storage.read_all()) == 3


@pytest.mark.anyio
async def test_in_memory_storage_concurrent_appends() -> None:
    """多协程并发追加条目时，asyncio.Lock 保证数据写入完整无竞争丢失。"""
    storage = InMemorySessionStorage()
    count = 50

    async def _append_worker(i: int) -> None:
        entry = MessageEntry(
            id=f"msg_{i}",
            message=Message(role="user", content=f"msg_{i}"),
        )
        await storage.append(entry)

    await asyncio.gather(*[_append_worker(i) for i in range(count)])

    stored = await storage.read_all()
    assert len(stored) == count
    stored_ids = {e.id for e in stored}
    assert stored_ids == {f"msg_{i}" for i in range(count)}


@pytest.mark.anyio
async def test_in_memory_storage_initial_entries() -> None:
    """InMemorySessionStorage 构造时支持传入初始条目。"""
    e0 = SessionInfoEntry(id="e0")
    m1 = MessageEntry(
        id="m1", parent_id="e0", message=Message(role="user", content="seed")
    )
    storage = InMemorySessionStorage(initial_entries=[e0, m1])

    entries = await storage.read_all()
    assert entries == [e0, m1]


def test_package_reexports_memory_and_storage() -> None:
    """验证 my_agent_core.session 统一导出 SessionState, SessionStorage, InMemorySessionStorage。"""
    from my_agent_core.session import (
        InMemorySessionStorage as ExportedInMemory,
    )
    from my_agent_core.session import (
        SessionState as ExportedSessionState,
    )
    from my_agent_core.session import (
        SessionStorage as ExportedSessionStorage,
    )

    assert ExportedSessionState is SessionState
    assert ExportedSessionStorage is SessionStorage
    assert ExportedInMemory is InMemorySessionStorage
