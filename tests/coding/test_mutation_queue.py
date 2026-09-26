import asyncio
from pathlib import Path
import pytest
from my_coding_agent.mutation_queue import FileMutationQueue


@pytest.mark.anyio
async def test_file_mutation_queue_serializes_same_file(tmp_path: Path):
    queue = FileMutationQueue()
    target_file = tmp_path / "shared.txt"

    execution_order = []
    active_count = 0
    max_concurrent = 0

    async def worker(task_id: int):
        nonlocal active_count, max_concurrent
        async with queue.acquire(target_file):
            active_count += 1
            max_concurrent = max(max_concurrent, active_count)
            execution_order.append(f"start_{task_id}")
            await asyncio.sleep(0.02)
            execution_order.append(f"end_{task_id}")
            active_count -= 1

    # Run 3 workers targeting the same file
    await asyncio.gather(worker(1), worker(2), worker(3))

    # Concurrency on the same file must never exceed 1
    assert max_concurrent == 1
    # Each start must immediately be followed by end before next start
    for i in range(0, len(execution_order), 2):
        start_id = execution_order[i].split("_")[1]
        end_id = execution_order[i + 1].split("_")[1]
        assert start_id == end_id


@pytest.mark.anyio
async def test_file_mutation_queue_parallel_for_different_files(tmp_path: Path):
    queue = FileMutationQueue()
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"

    active_count = 0
    max_concurrent = 0

    async def worker(target_file: Path):
        nonlocal active_count, max_concurrent
        async with queue.acquire(target_file):
            active_count += 1
            max_concurrent = max(max_concurrent, active_count)
            await asyncio.sleep(0.04)
            active_count -= 1

    # Run 2 workers targeting different files
    await asyncio.gather(worker(file_a), worker(file_b))

    # Workers on different files must be able to run concurrently
    assert max_concurrent == 2


@pytest.mark.anyio
async def test_file_mutation_queue_releases_lock_on_exception(tmp_path: Path):
    queue = FileMutationQueue()
    target_file = tmp_path / "error_test.txt"

    # Worker 1 raises an exception
    with pytest.raises(RuntimeError, match="disk error"):
        async with queue.acquire(target_file):
            raise RuntimeError("disk error")

    # Worker 2 should immediately be able to acquire the lock without deadlocking
    acquired = False
    async with queue.acquire(target_file):
        acquired = True

    assert acquired is True
