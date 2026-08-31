import asyncio
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from my_agent_core.task_store import TaskStore  # pyright: ignore[reportMissingImports]


def test_task_store_create_and_get(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        t1 = await store.create(
            subject="Design schema", description="Create users table"
        )
        assert t1.id == "task_1"
        assert t1.status == "pending"
        assert t1.subject == "Design schema"
        assert store.get("task_1").description == "Create users table"

    asyncio.run(_test())


def test_task_store_dag_dependencies_and_unblock(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        await store.create(subject="Task 1")
        await store.create(subject="Task 2")

        # t2 blocked by t1
        updated_t2, unblocked = await store.update("task_2", add_blocked_by=["task_1"])
        assert updated_t2.blocked_by == ["task_1"]
        assert unblocked == []

        # Complete t1 -> t2 should unblock
        updated_t1, unblocked = await store.update("task_1", status="completed")
        assert updated_t1.status == "completed"
        assert "task_2" in unblocked

    asyncio.run(_test())


def test_task_store_cycle_detection(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        await store.create(subject="Task 1")
        await store.create(subject="Task 2")
        await store.update("task_2", add_blocked_by=["task_1"])

        with pytest.raises(ValueError, match="[Cc]ycle"):
            await store.update("task_1", add_blocked_by=["task_2"])

    asyncio.run(_test())


def test_task_store_single_in_progress_enforcement(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path, enforce_single_in_progress=True)
        await store.create(subject="Task 1")
        await store.create(subject="Task 2")

        await store.update("task_1", status="in_progress")
        with pytest.raises(ValueError, match="already in progress"):
            await store.update("task_2", status="in_progress")

    asyncio.run(_test())


def test_task_store_render_board(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        await store.create(subject="Task 1")
        await store.create(subject="Task 2")
        await store.update("task_1", status="completed")
        await store.update("task_2", status="in_progress", active_form="writing code")

        board = store.render_board()
        assert "[x] task_1: Task 1" in board
        assert "[>] task_2: Task 2" in board
        assert "writing code" in board

    asyncio.run(_test())


def test_task_store_persistence(tmp_path: Path):
    async def _test():
        store1 = TaskStore(tmp_path)
        await store1.create(subject="Persisted task")

        store2 = TaskStore(tmp_path)
        assert len(store2.list()) == 1
        assert store2.get("task_1").subject == "Persisted task"

    asyncio.run(_test())


def test_task_store_batch_write(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        items = await store.batch_write(
            [
                {"subject": "Batch task 1", "status": "completed"},
                {"subject": "Batch task 2", "status": "in_progress"},
            ]
        )
        assert len(items) == 2
        assert store.get("task_1").status == "completed"
        assert store.get("task_2").status == "in_progress"

    asyncio.run(_test())


def test_task_store_invalid_operations(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        with pytest.raises(ValueError, match="cannot be empty"):
            await store.create(subject="   ")

        with pytest.raises(KeyError, match="not found"):
            store.get("task_999")

        with pytest.raises(KeyError, match="not found"):
            await store.update("task_999", status="completed")

        await store.create(subject="Task 1")
        with pytest.raises(ValueError, match="cannot depend on itself"):
            await store.update("task_1", add_blocked_by=["task_1"])

        with pytest.raises(KeyError, match="not found"):
            await store.update("task_1", add_blocked_by=["task_nonexistent"])

    asyncio.run(_test())


def test_task_store_parallel_concurrency_stress(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)

        # 1. 20 concurrent creates
        tasks = await asyncio.gather(
            *(store.create(subject=f"Concurrent Task {i}") for i in range(20))
        )
        assert len(tasks) == 20
        unique_ids = {t.id for t in tasks}
        assert len(unique_ids) == 20
        assert len(store.list()) == 20

        # 2. 20 concurrent updates on distinct tasks
        update_results = await asyncio.gather(
            *(store.update(f"task_{i + 1}", description=f"Desc {i}") for i in range(20))
        )
        assert len(update_results) == 20
        for i in range(20):
            assert store.get(f"task_{i + 1}").description == f"Desc {i}"

        # 3. Reload from disk and verify consistency
        reloaded = TaskStore(tmp_path)
        assert len(reloaded.list()) == 20

    asyncio.run(_test())
