"""Pure append-only session storage protocol and in-memory implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .entries import SessionEntry


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


__all__ = [
    "SessionStorage",
    "InMemorySessionStorage",
]
