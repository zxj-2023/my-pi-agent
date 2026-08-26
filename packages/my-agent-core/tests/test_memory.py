"""Unit tests for MemoryStore (Phase 7 - Memory System)."""

import tempfile
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from my_agent_core.memory import (
    ENTRY_DELIMITER,
    MEMORY_CHAR_LIMIT,
    USER_CHAR_LIMIT,
    MemoryStore,
    make_memory_tool,
)


def test_memory_store_constants():
    assert ENTRY_DELIMITER == "\n§\n"
    assert MEMORY_CHAR_LIMIT == 2200
    assert USER_CHAR_LIMIT == 1375


def test_memory_store_load_and_frozen_snapshot():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_dir = Path(tmpdir)
        (mem_dir / "MEMORY.md").write_text("Fact 1\n§\nFact 2", encoding="utf-8-sig")
        (mem_dir / "USER.md").write_text("User prefers Python", encoding="utf-8-sig")

        store = MemoryStore(mem_dir=mem_dir)
        store.load_from_disk()

        assert store.format_for_system_prompt("memory") == "Fact 1\n§\nFact 2"
        assert store.format_for_system_prompt("user") == "User prefers Python"

        xml = store.format_all_for_system_prompt()
        assert xml is not None
        assert "<MEMORY_CONTEXT>" in xml
        assert "## MEMORY.md (Agent Notes)\nFact 1\n§\nFact 2" in xml
        assert "## USER.md (User Profile)\nUser prefers Python" in xml
        assert "</MEMORY_CONTEXT>" in xml

        # 验证冻结快照不变性：add 更改 live 数据后，format_for_system_prompt 保持不变
        res = store.add("memory", "Fact 3")
        assert "Added to memory" in res
        assert store.format_for_system_prompt("memory") == "Fact 1\n§\nFact 2"

        # 验证磁盘已经落盘
        disk_content = (mem_dir / "MEMORY.md").read_text(encoding="utf-8-sig")
        assert disk_content == "Fact 1\n§\nFact 2\n§\nFact 3"


def test_memory_store_empty_or_missing_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent_dir = Path(tmpdir) / "sub" / "memory"
        store = MemoryStore(mem_dir=non_existent_dir)
        store.load_from_disk()

        assert store.format_for_system_prompt("memory") is None
        assert store.format_for_system_prompt("user") is None
        assert store.format_all_for_system_prompt() is None

        # 写入时自动创建父目录
        res = store.add("memory", "New fact")
        assert "Added to memory" in res
        assert (non_existent_dir / "MEMORY.md").exists()


def test_memory_store_deduplication_and_bom_tolerance():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_dir = Path(tmpdir)
        # 带有 BOM 头的 UTF-8-SIG，且包含重复项和空白项
        raw_text = "\ufeffEntry A\n§\nEntry B\n§\nEntry A\n§\n   \n§\nEntry C"
        (mem_dir / "MEMORY.md").write_bytes(raw_text.encode("utf-8"))

        store = MemoryStore(mem_dir=mem_dir)
        store.load_from_disk()

        assert (
            store.format_for_system_prompt("memory")
            == "Entry A\n§\nEntry B\n§\nEntry C"
        )


def test_memory_store_add_validation_and_limits():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(mem_dir=tmpdir, memory_char_limit=50, user_char_limit=30)
        store.load_from_disk()

        # 无效 target 校验
        assert "Invalid target" in store.add("invalid_target", "content")

        # 空内容拒绝
        assert "Content cannot be empty" in store.add("memory", "   ")

        # 正常添加
        res = store.add("memory", "Short fact")
        assert "Added to memory" in res
        assert "(10/50 chars used)" in res

        # 精确重复拒绝
        assert "Entry already exists in memory" in store.add("memory", "Short fact")

        # 超限拒绝（50 字符上限，当前 10 字符 + "\n§\n" 3 字符 + 40 字符 = 53 字符 > 50）
        overflow_content = "X" * 40
        res_overflow = store.add("memory", overflow_content)
        assert (
            "Cannot add: total length (53) exceeds limit (50) for memory"
            in res_overflow
        )
        assert "Please consolidate or remove older entries first." in res_overflow
        assert "Current entries:\nShort fact" in res_overflow


def test_memory_store_replace():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_dir = Path(tmpdir)
        (mem_dir / "MEMORY.md").write_text(
            "First item\n§\nSecond item\n§\nSecond duplicate key", encoding="utf-8"
        )
        store = MemoryStore(mem_dir=mem_dir, memory_char_limit=100)
        store.load_from_disk()

        # 无效 target
        assert "Invalid target" in store.replace("invalid", "old", "new")

        # 空 old_text / new_content
        assert "old_text cannot be empty" in store.replace("memory", "   ", "new")
        assert "new_content cannot be empty" in store.replace("memory", "First", "   ")

        # 唯原子串替换
        res = store.replace("memory", "First", "Updated first item")
        assert "Replaced in memory" in res

        # 未命中报错
        assert "Text 'NonExistent' not found in memory" in store.replace(
            "memory", "NonExistent", "New"
        )

        # 歧义多处命中报错
        res_ambiguous = store.replace("memory", "Second", "New second")
        assert (
            "Ambiguous match: found 2 entries matching 'Second' in memory"
            in res_ambiguous
        )
        assert "Second item" in res_ambiguous
        assert "Second duplicate key" in res_ambiguous

        # 超限拒绝
        res_overflow = store.replace("memory", "Updated first", "Y" * 120)
        assert "Cannot replace: total length" in res_overflow
        assert "exceeds limit" in res_overflow

        # 验证磁盘状态
        disk_content = (mem_dir / "MEMORY.md").read_text(encoding="utf-8-sig")
        assert (
            disk_content
            == "Updated first item\n§\nSecond item\n§\nSecond duplicate key"
        )


def test_memory_store_remove():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_dir = Path(tmpdir)
        (mem_dir / "USER.md").write_text(
            "Prefers concise code\n§\nPrefers async\n§\nPrefers tabs", encoding="utf-8"
        )
        store = MemoryStore(mem_dir=mem_dir)
        store.load_from_disk()

        # 无效 target
        assert "Invalid target" in store.remove("invalid", "old")

        # 空 old_text
        assert "old_text cannot be empty" in store.remove("user", "  ")

        # 未命中
        assert "Text 'Not here' not found in user" in store.remove("user", "Not here")

        # 歧义匹配（"Prefers" 命中全部 3 条）
        res_ambiguous = store.remove("user", "Prefers")
        assert (
            "Ambiguous match: found 3 entries matching 'Prefers' in user"
            in res_ambiguous
        )

        # 唯原子串删除
        res_del = store.remove("user", "async")
        assert "Removed from user" in res_del

        # 验证磁盘状态
        disk_content = (mem_dir / "USER.md").read_text(encoding="utf-8-sig")
        assert disk_content == "Prefers concise code\n§\nPrefers tabs"


def test_format_all_for_system_prompt_partial():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_dir = Path(tmpdir)
        (mem_dir / "USER.md").write_text("Prefers dark mode", encoding="utf-8")
        store = MemoryStore(mem_dir=mem_dir)
        store.load_from_disk()

        xml = store.format_all_for_system_prompt()
        assert xml is not None
        assert "## USER.md (User Profile)\nPrefers dark mode" in xml
        assert "## MEMORY.md" not in xml


@pytest.mark.anyio
async def test_make_memory_tool_schema_and_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_dir = Path(tmpdir)
        store = MemoryStore(mem_dir=mem_dir)
        store.load_from_disk()

        tool = make_memory_tool(store)
        assert tool.name == "memory"
        assert "Manage long-term memory across sessions" in tool.description

        # 检查 Function Calling Schema
        schema = tool.to_openai_schema()
        assert schema["function"]["name"] == "memory"
        props = schema["function"]["parameters"]["properties"]
        assert "target" in props
        assert "action" in props
        assert "content" in props
        assert "old_text" in props
        assert "new_content" in props

        # 1. 测试 execute add
        res_add = await tool.execute(
            {"target": "user", "action": "add", "content": "User likes concise code"}
        )
        assert res_add.ok is True
        assert "Added to user" in str(res_add.data)
        assert (mem_dir / "USER.md").exists()

        # 2. 测试 execute replace (使用 new_content)
        res_rep = await tool.execute(
            {
                "target": "user",
                "action": "replace",
                "old_text": "concise",
                "new_content": "User likes async and concise code",
            }
        )
        assert res_rep.ok is True
        assert "Replaced in user" in str(res_rep.data)

        # 3. 测试 execute replace (回退使用 content 作为 new_content)
        res_rep_fallback = await tool.execute(
            {
                "target": "user",
                "action": "replace",
                "old_text": "async and ",
                "content": "User likes ultra-concise code",
            }
        )
        assert res_rep_fallback.ok is True
        assert "Replaced in user" in str(res_rep_fallback.data)

        # 4. 测试 execute remove
        res_rem = await tool.execute(
            {"target": "user", "action": "remove", "old_text": "ultra-concise"}
        )
        assert res_rem.ok is True
        assert "Removed from user" in str(res_rem.data)


@pytest.mark.anyio
async def test_make_memory_tool_never_throw_validation_errors():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(mem_dir=tmpdir)
        store.load_from_disk()
        tool = make_memory_tool(store)

        # add 缺少 content
        res1 = await tool.execute({"target": "memory", "action": "add"})
        assert res1.ok is False
        assert "`content` is required when action is 'add'" in (res1.error or "")

        # replace 缺少 old_text
        res2 = await tool.execute(
            {"target": "memory", "action": "replace", "new_content": "new"}
        )
        assert res2.ok is False
        assert "`old_text` is required when action is 'replace'" in (
            res2.error or ""
        )

        # replace 缺少 new_content 和 content
        res3 = await tool.execute(
            {"target": "memory", "action": "replace", "old_text": "old"}
        )
        assert res3.ok is False
        assert "`new_content` is required when action is 'replace'" in (
            res3.error or ""
        )

        # remove 缺少 old_text
        res4 = await tool.execute({"target": "memory", "action": "remove"})
        assert res4.ok is False
        assert "`old_text` is required when action is 'remove'" in (
            res4.error or ""
        )

        # 未知 action
        res5 = await tool.execute(
            {"target": "memory", "action": "unknown_action"}
        )
        assert res5.ok is False

