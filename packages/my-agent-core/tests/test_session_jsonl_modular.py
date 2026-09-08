"""Unit tests for modular JSONL append-only storage and legacy format migration.

Tests:
1. Serialization and deserialization of 9 SessionEntry types via entry_to_json_line / entry_from_json_line.
2. Legacy format migration (v1 header, legacy message, legacy compaction).
3. SessionJsonlError error handling (blank lines, corrupt JSON, invalid schema).
4. JsonlSessionStorage append, append_batch, and read_all round-trip.
5. Auto-cleanup of incomplete .tmp fragments (_remove_incomplete_temp).
6. Toleration of torn last line and rejection of middle corruption.
7. Cross-process concurrency with .<name>.lock.
8. Package re-exports from my_agent_core.session.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

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
from my_agent_core.session.jsonl import (
    JsonlSessionStorage,
    SessionJsonlError,
    entry_from_json_line,
    entry_to_json_line,
)

# ============================================================================
# 1. 强类型 SessionEntry 序列化与反序列化
# ============================================================================


def test_serialize_and_deserialize_all_9_entry_types() -> None:
    """9 种 SessionEntry 通过 entry_to_json_line 和 entry_from_json_line 往返恢复。"""
    e0 = SessionInfoEntry(id="info1", cwd="/test/dir", title="Test Session")
    e1 = MessageEntry(
        id="m1",
        parent_id="info1",
        message=Message(role="user", content="hello"),
    )
    e2 = ModelChangeEntry(
        id="mc1",
        parent_id="m1",
        model="gpt-4o",
        provider="openai",
    )
    e3 = ThinkingLevelChangeEntry(
        id="tc1",
        parent_id="mc1",
        thinking_level="high",
    )
    e4 = CompactionEntry(
        id="c1",
        parent_id="tc1",
        summary="summary of conversation",
        replaces_entry_ids=["m1"],
    )
    e5 = BranchSummaryEntry(
        id="b1",
        parent_id="c1",
        summary="explored alternative approach",
        details={"result": "ok"},
    )
    e6 = LabelEntry(
        id="l1",
        parent_id="b1",
        label="checkpoint-1",
        target_id="m1",
    )
    e7 = LeafEntry(
        id="lf1",
        parent_id="l1",
        leaf_id="l1",
    )
    e8 = CustomEntry(
        id="cust1",
        parent_id="lf1",
        namespace="telemetry",
        data={"metric": 42},
    )

    all_entries = [e0, e1, e2, e3, e4, e5, e6, e7, e8]

    for original in all_entries:
        line = entry_to_json_line(original)
        assert isinstance(line, str)
        assert "\n" not in line.strip()

        recovered = entry_from_json_line(line)
        assert isinstance(recovered, type(original))
        assert recovered.id == original.id
        assert recovered.parent_id == original.parent_id


def test_entry_to_json_line_and_from_json_line_aliases() -> None:
    """验证 camelCase 与 snake_case 在序列化反序列化中的透明兼容。"""
    entry = MessageEntry(
        id="m1",
        parent_id="root",
        message=Message(role="assistant", content="done"),
    )
    line = entry_to_json_line(entry)
    data = json.loads(line)
    assert data["parentId"] == "root"

    # snake_case 手动传入也能正确解析
    snake_json = json.dumps(
        {
            "type": "message",
            "id": "m2",
            "parent_id": "root2",
            "message": {"role": "user", "content": "hi"},
        }
    )
    recovered = entry_from_json_line(snake_json)
    assert isinstance(recovered, MessageEntry)
    assert recovered.parent_id == "root2"


# ============================================================================
# 2. 遗留格式向下兼容迁移 (_migrate_session_entry)
# ============================================================================


def test_migrate_legacy_header_without_type() -> None:
    """旧版 Header（无 type 字段，含 id, created_at, cwd, current_id, root_id）能迁移为 SessionInfoEntry。"""
    legacy_header = json.dumps(
        {
            "id": "20260830-120000-abcd1234",
            "created_at": "2026-08-30T12:00:00.000000",
            "cwd": "/workspace/project",
            "current_id": "m1",
            "root_id": "m0",
            "compaction_floor": "m1",
            "metadata": {"custom_meta": 1},
        }
    )
    entry = entry_from_json_line(legacy_header)
    assert isinstance(entry, SessionInfoEntry)
    assert entry.id == "20260830-120000-abcd1234"
    assert entry.cwd == "/workspace/project"
    assert entry.metadata["current_id"] == "m1"
    assert entry.metadata["root_id"] == "m0"
    assert entry.metadata["compaction_floor"] == "m1"
    assert entry.metadata["custom_meta"] == 1


def test_migrate_legacy_header_with_type_session() -> None:
    """带 type='session' 与 version=1 的旧版 Header 迁移为 SessionInfoEntry。"""
    legacy_header = json.dumps(
        {
            "type": "session",
            "version": 1,
            "id": "s-legacy",
            "created_at": "2026-08-01T00:00:00",
            "cwd": ".",
            "current_id": None,
            "root_id": None,
        }
    )
    entry = entry_from_json_line(legacy_header)
    assert isinstance(entry, SessionInfoEntry)
    assert entry.id == "s-legacy"
    assert entry.cwd == "."


def test_migrate_legacy_message_entry() -> None:
    """旧版 Message 条目（扁平 role, content, metadata，无嵌套 message 对象）能迁移为 MessageEntry。"""
    legacy_msg = json.dumps(
        {
            "id": "msg-old",
            "parent_id": "msg-root",
            "timestamp": "2026-08-30T12:01:00",
            "role": "assistant",
            "content": "thinking output",
            "metadata": {
                "tool_calls": [
                    {"id": "tc1", "type": "function", "function": {"name": "read"}}
                ],
            },
        }
    )
    entry = entry_from_json_line(legacy_msg)
    assert isinstance(entry, MessageEntry)
    assert entry.id == "msg-old"
    assert entry.parent_id == "msg-root"
    assert entry.message.role == "assistant"
    assert entry.message.content == "thinking output"
    assert entry.message.metadata is not None
    assert "tool_calls" in entry.message.metadata


def test_migrate_legacy_compaction_entry() -> None:
    """旧版 Compaction 条目（使用 content 存放 summary 文本，role='system'）能迁移为 CompactionEntry。"""
    legacy_compaction = json.dumps(
        {
            "type": "compaction",
            "id": "comp-old",
            "parent_id": "prev-1",
            "role": "system",
            "content": "## Summary of previous steps",
            "metadata": {
                "covered_count": 5,
                "tokens_before": 10000,
            },
        }
    )
    entry = entry_from_json_line(legacy_compaction)
    assert isinstance(entry, CompactionEntry)
    assert entry.id == "comp-old"
    assert entry.summary == "## Summary of previous steps"
    assert entry.metadata["covered_count"] == 5


# ============================================================================
# 3. 错误处理与门禁 (SessionJsonlError)
# ============================================================================


def test_entry_from_json_line_rejects_empty_and_corrupt() -> None:
    """空行、纯空白字符或非合法 JSON 均抛出 SessionJsonlError。"""
    with pytest.raises(SessionJsonlError):
        entry_from_json_line("")

    with pytest.raises(SessionJsonlError):
        entry_from_json_line("   \n")

    with pytest.raises(SessionJsonlError):
        entry_from_json_line("not-json-at-all")

    with pytest.raises(SessionJsonlError):
        entry_from_json_line("[1, 2, 3]")  # JSON 数组不是 entry 对象


def test_entry_from_json_line_rejects_invalid_schema() -> None:
    """字段缺失或类型冲突且非遗留格式的 JSON 抛出 SessionJsonlError。"""
    with pytest.raises(SessionJsonlError):
        entry_from_json_line(json.dumps({"type": "invalid_type", "id": "123"}))


# ============================================================================
# 4. JsonlSessionStorage 追加写入与读取 (Append & Read)
# ============================================================================


@pytest.mark.anyio
async def test_jsonl_storage_append_and_read_all(tmp_path: Path) -> None:
    """测试单个 append 与 read_all 正确往返。"""
    file_path = tmp_path / "test_session.jsonl"
    storage = JsonlSessionStorage(file_path)

    e0 = SessionInfoEntry(id="info1", cwd=str(tmp_path))
    m1 = MessageEntry(
        id="m1", parent_id="info1", message=Message(role="user", content="hello")
    )

    await storage.append(e0)
    await storage.append(m1)

    # 验证磁盘行数
    lines = file_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    # 验证读取恢复
    entries = await storage.read_all()
    assert len(entries) == 2
    assert isinstance(entries[0], SessionInfoEntry)
    assert isinstance(entries[1], MessageEntry)
    assert entries[0].id == "info1"
    assert entries[1].message.content == "hello"


@pytest.mark.anyio
async def test_jsonl_storage_append_batch(tmp_path: Path) -> None:
    """测试 append_batch 原子追加多个条目。"""
    file_path = tmp_path / "batch.jsonl"
    storage = JsonlSessionStorage(file_path)

    batch = [
        SessionInfoEntry(id="i1", cwd="."),
        MessageEntry(
            id="m1", parent_id="i1", message=Message(role="user", content="q1")
        ),
        MessageEntry(
            id="m2", parent_id="m1", message=Message(role="assistant", content="a1")
        ),
    ]
    await storage.append_batch(batch)

    entries = await storage.read_all()
    assert len(entries) == 3
    assert [e.id for e in entries] == ["i1", "m1", "m2"]


@pytest.mark.anyio
async def test_jsonl_storage_non_existent_file_returns_empty(tmp_path: Path) -> None:
    """不存在的文件 read_all 返回空列表，不抛异常。"""
    storage = JsonlSessionStorage(tmp_path / "non_existent.jsonl")
    entries = await storage.read_all()
    assert entries == []


# ============================================================================
# 5. 碎片自愈自清理 (_remove_incomplete_temp)
# ============================================================================


@pytest.mark.anyio
async def test_jsonl_storage_removes_incomplete_temp_on_init(tmp_path: Path) -> None:
    """初始化 JsonlSessionStorage 时自动清理遗留的未提交 .tmp 文件。"""
    session_file = tmp_path / "session_active.jsonl"
    tmp_remnant_1 = tmp_path / ".session_active.jsonl.12345.tmp"
    tmp_remnant_2 = tmp_path / ".session_active.jsonl.abc.tmp"
    unrelated_tmp = tmp_path / "other_agent.tmp"

    tmp_remnant_1.write_text("corrupted 1", encoding="utf-8")
    tmp_remnant_2.write_text("corrupted 2", encoding="utf-8")
    unrelated_tmp.write_text("keep me", encoding="utf-8")

    storage = JsonlSessionStorage(session_file)
    assert storage.path == session_file
    assert not tmp_remnant_1.exists()
    assert not tmp_remnant_2.exists()
    # 无关 tmp 文件保持原样
    assert unrelated_tmp.exists()


@pytest.mark.anyio
async def test_jsonl_storage_removes_temp_on_append(tmp_path: Path) -> None:
    """在 append 执行期间也能自愈清理中途产生的 .tmp 碎片。"""
    session_file = tmp_path / "session_append.jsonl"
    storage = JsonlSessionStorage(session_file)

    await storage.append(SessionInfoEntry(id="i1", cwd="."))

    # 模拟外部异常遗留的碎片
    tmp_file = tmp_path / ".session_append.jsonl.ghost.tmp"
    tmp_file.write_text("ghost data", encoding="utf-8")
    assert tmp_file.exists()

    await storage.append(
        MessageEntry(
            id="m1", parent_id="i1", message=Message(role="user", content="hi")
        )
    )
    assert not tmp_file.exists()


# ============================================================================
# 6. 尾行撕裂容忍与中间行损坏检查
# ============================================================================


@pytest.mark.anyio
async def test_jsonl_storage_tolerates_torn_last_line(tmp_path: Path) -> None:
    """文件末尾撕裂（未写完的半行 JSON）在 read_all 时被自动宽容丢弃。"""
    file_path = tmp_path / "torn.jsonl"
    storage = JsonlSessionStorage(file_path)

    e0 = SessionInfoEntry(id="i1", cwd=".")
    m1 = MessageEntry(
        id="m1", parent_id="i1", message=Message(role="user", content="fine")
    )
    await storage.append_batch([e0, m1])

    # 手动在文件末尾追加半截撕裂行
    with open(file_path, "a", encoding="utf-8") as f:
        f.write('{"id": "torn_row", "type": "mess')

    entries = await storage.read_all()
    assert len(entries) == 2
    assert entries[-1].id == "m1"


@pytest.mark.anyio
async def test_jsonl_storage_rejects_corrupted_middle_line(tmp_path: Path) -> None:
    """如果损坏发生在中间行而非尾行，read_all 抛出 SessionJsonlError。"""
    file_path = tmp_path / "corrupted_middle.jsonl"
    storage = JsonlSessionStorage(file_path)

    e0 = SessionInfoEntry(id="i1", cwd=".")
    m1 = MessageEntry(
        id="m1", parent_id="i1", message=Message(role="user", content="ok")
    )
    await storage.append_batch([e0, m1])

    # 在中间插入损坏行，最后仍有有效行
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(entry_to_json_line(e0) + "\n")
        f.write("corrupted line that is not valid json\n")
        f.write(entry_to_json_line(m1) + "\n")

    with pytest.raises(SessionJsonlError):
        await storage.read_all()


# ============================================================================
# 7. 多进程锁竞争安全排队 (Cross-Process Locking)
# ============================================================================


def _mp_worker(path_str: str, worker_id: int, count: int) -> None:
    """多进程工作子进程，使用 asyncio 运行 append 操作。"""
    import asyncio

    async def _run() -> None:
        store = JsonlSessionStorage(Path(path_str))
        for i in range(count):
            entry = MessageEntry(
                id=f"w{worker_id}_{i}",
                parent_id="root",
                message=Message(role="user", content=f"worker {worker_id} msg {i}"),
            )
            await store.append(entry)

    asyncio.run(_run())


def test_cross_process_locking_concurrency(tmp_path: Path) -> None:
    """两个进程同时高频写入同一个 JSONL 文件，锁确保数据不撕裂且全量写入。"""
    session_file = tmp_path / "concurrent_session.jsonl"
    lock_file = tmp_path / ".concurrent_session.jsonl.lock"

    # 先写入根 SessionInfoEntry
    storage = JsonlSessionStorage(session_file)
    assert storage.lock_path == lock_file

    import asyncio

    asyncio.run(storage.append(SessionInfoEntry(id="root", cwd=".")))

    p1 = mp.Process(target=_mp_worker, args=(str(session_file), 1, 5))
    p2 = mp.Process(target=_mp_worker, args=(str(session_file), 2, 5))

    p1.start()
    p2.start()

    p1.join(timeout=10)
    p2.join(timeout=10)

    assert p1.exitcode == 0
    assert p2.exitcode == 0

    # 验证读取所有条目（1 + 5 + 5 = 11 条）
    entries = asyncio.run(storage.read_all())
    assert len(entries) == 11
    ids = {e.id for e in entries}
    assert "root" in ids
    for i in range(5):
        assert f"w1_{i}" in ids
        assert f"w2_{i}" in ids


# ============================================================================
# 8. 门面统一导出验证
# ============================================================================


def test_package_reexports_jsonl_subsystem() -> None:
    """验证 my_agent_core.session 统一导出 JsonlSessionStorage, SessionJsonlError 等。"""
    from my_agent_core.session import (
        JsonlSessionStorage as ExportedJsonlStorage,
    )
    from my_agent_core.session import (
        SessionJsonlError as ExportedError,
    )
    from my_agent_core.session import (
        entry_from_json_line as exported_from_line,
    )
    from my_agent_core.session import (
        entry_to_json_line as exported_to_line,
    )

    assert ExportedJsonlStorage is JsonlSessionStorage
    assert ExportedError is SessionJsonlError
    assert exported_to_line is entry_to_json_line
    assert exported_from_line is entry_from_json_line


@pytest.mark.anyio
async def test_interop_legacy_session_file_read_by_jsonl_storage(
    tmp_path: Path,
) -> None:
    """使用 legacy Session 保存文件后，JsonlSessionStorage 能无缝读取其全量历史。"""
    from my_agent_core.session import Session

    file_path = tmp_path / "legacy_interop.jsonl"
    session = Session(path=file_path)
    session.add_message("user", "how are you?")
    session.add_message("assistant", "I am fine!")
    session.add_summary_cache(
        "## Summary",
        covered_count=2,
        retained_tail=[{"role": "assistant", "content": "I am fine!"}],
        tokens_before=100,
    )

    # 用 JsonlSessionStorage 直接加载
    storage = JsonlSessionStorage(file_path)
    entries = await storage.read_all()

    assert len(entries) == 4
    assert isinstance(entries[0], SessionInfoEntry)
    assert entries[0].id == session.id
    assert isinstance(entries[1], MessageEntry)
    assert entries[1].message.role == "user"
    assert entries[1].message.content == "how are you?"
    assert isinstance(entries[2], MessageEntry)
    assert entries[2].message.role == "assistant"
    assert entries[2].message.content == "I am fine!"
    assert isinstance(entries[3], CompactionEntry)
    assert entries[3].summary == "## Summary"
