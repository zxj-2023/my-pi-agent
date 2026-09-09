# pyright: reportUnusedCallResult=false
"""Locked, append-only session storage implementations and protocols.

对齐 Tau (tau_agent.session.storage) 架构设计：
集中放置 SessionStorage 协议、InMemorySessionStorage 以及 JsonlSessionStorage。
文件锁底层调用以内聚辅助函数 _lock_file / _unlock_file 放置于文件末尾，
彻底杜绝模块顶层的条件分支定义，具备工业级跨进程防踩踏与超时保护能力。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from .entries import SessionEntry
from .jsonl import (
    SessionJsonlError,
    entry_from_json_line,
    entry_to_json_line,
)


@runtime_checkable
class SessionStorage(Protocol):
    """纯异步只追加会话存储协议。

    彻底废除全量重写 rewrite_history，保证历史记录发生即不可变。
    """

    async def append(self, entry: SessionEntry) -> None:
        """追加单个条目到存储末尾。"""
        ...

    async def append_batch(self, entries: Sequence[SessionEntry]) -> None:
        """原子追加一批条目到存储末尾。"""
        ...

    async def read_all(self) -> list[SessionEntry]:
        """读取存储中所有按追加时序排列的历史条目。"""
        ...


class InMemorySessionStorage:
    """纯内存只追加会话存储实现。

    用于极速单元测试和无持久化需求的会话场景，协程安全。
    """

    def __init__(self, initial_entries: Sequence[SessionEntry] | None = None) -> None:
        self._entries: list[SessionEntry] = (
            list(initial_entries) if initial_entries else []
        )
        self._lock = asyncio.Lock()

    async def append(self, entry: SessionEntry) -> None:
        async with self._lock:
            self._entries.append(entry)

    async def append_batch(self, entries: Sequence[SessionEntry]) -> None:
        async with self._lock:
            self._entries.extend(entries)

    async def read_all(self) -> list[SessionEntry]:
        async with self._lock:
            return list(self._entries)


class JsonlSessionStorage:
    """基于单文件行级追加的 SessionStorage 实现。

    支持 `.{name}.lock` 跨进程文件锁，以及异常退出遗留 `.tmp` 碎片的自愈清理。
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.lock_path = self.path.parent / f".{self.path.name}.lock"
        self._async_lock = asyncio.Lock()
        self._remove_incomplete_temp()

    def _remove_incomplete_temp(self) -> list[Path]:
        """清理异常中断遗留的临时碎片文件。"""
        cleaned: list[Path] = []
        parent = self.path.parent
        if not parent.exists():
            return cleaned

        patterns = [
            f".{self.path.name}*.tmp",
            f"{self.path.name}*.tmp",
        ]
        seen: set[Path] = set()
        for pattern in patterns:
            for tmp_file in parent.glob(pattern):
                if tmp_file in seen or not tmp_file.is_file():
                    continue
                seen.add(tmp_file)
                with contextlib.suppress(OSError):
                    tmp_file.unlink(missing_ok=True)
                    cleaned.append(tmp_file)
        return cleaned

    @contextlib.asynccontextmanager
    async def _process_lock(self, timeout: float = 10.0) -> AsyncIterator[None]:
        """基于 `.{name}.lock` 的跨进程文件锁。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.monotonic()
        fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT)
        try:
            acquired = False
            while not acquired:
                try:
                    _lock_file(fd)
                    acquired = True
                except (BlockingIOError, OSError, PermissionError):
                    if time.monotonic() - start_time > timeout:
                        raise SessionJsonlError(
                            f"Timeout ({timeout}s) waiting for lock on {self.lock_path}"
                        ) from None
                    await asyncio.sleep(0.01)
            try:
                yield
            finally:
                _unlock_file(fd)
        finally:
            os.close(fd)

    @contextlib.asynccontextmanager
    async def _lock(self, timeout: float = 10.0) -> AsyncIterator[None]:
        """协程锁与跨进程锁的双重上下文。"""
        async with self._async_lock, self._process_lock(timeout=timeout):
            yield

    async def append(self, entry: SessionEntry) -> None:
        """追加单个条目到存储末尾。"""
        async with self._lock():
            self._remove_incomplete_temp()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = entry_to_json_line(entry)
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except OSError as exc:
                raise SessionJsonlError(
                    f"Failed to append to {self.path}: {exc}"
                ) from exc

    async def append_batch(self, entries: Sequence[SessionEntry]) -> None:
        """原子追加一批条目到存储末尾。"""
        if not entries:
            return
        async with self._lock():
            self._remove_incomplete_temp()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lines = [entry_to_json_line(e) for e in entries]
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    for line in lines:
                        f.write(line + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except OSError as exc:
                raise SessionJsonlError(
                    f"Failed to append batch to {self.path}: {exc}"
                ) from exc

    async def read_all(self) -> list[SessionEntry]:
        """读取存储中所有按追加时序排列的历史条目。"""
        async with self._lock():
            self._remove_incomplete_temp()
            if not self.path.exists():
                return []

            try:
                with open(self.path, encoding="utf-8") as f:
                    raw_lines = f.readlines()
            except OSError as exc:
                raise SessionJsonlError(
                    f"Failed to read {self.path}: {exc}"
                ) from exc

            lines = [ln.strip() for ln in raw_lines if ln.strip()]
            if not lines:
                return []

            entries: list[SessionEntry] = []
            for i, line in enumerate(lines):
                is_last = i == len(lines) - 1
                try:
                    entry = entry_from_json_line(line)
                    entries.append(entry)
                except SessionJsonlError as exc:
                    # 尾行撕裂容忍：如果是最后一行且前面已有有效条目，丢弃该损坏尾行（宽容兜底）
                    if _should_tolerate_tail_error(is_last, len(entries)):
                        break
                    raise exc
            return entries


# ─── 私有辅助函数（对齐 Tau 内聚风格，置于模块末尾） ──────────────────────────


def _should_tolerate_tail_error(is_last: bool, count: int) -> bool:
    """尾行撕裂容忍：最后一行且前面已有有效条目时为 True。"""
    return is_last and count > 0


def _lock_file(fd: int) -> None:
    """底层文件锁适配（非阻塞排他锁），内部按需判断操作系统。"""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(fd: int) -> None:
    """底层文件解锁适配。"""
    if sys.platform == "win32":
        import msvcrt

        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)


__all__ = [
    "SessionStorage",
    "InMemorySessionStorage",
    "JsonlSessionStorage",
]
