"""文件变更互斥锁队列 (FileMutationQueue) —— 细粒度单文件写锁管理。

允许不同文件的写操作完全并发，同名文件的写操作自动保序排队，兼具极致性能与并发安全。
"""

from __future__ import annotations

import asyncio
from pathlib import Path


class FileMutationQueue:
    """管理针对特定文件绝对路径的异步互斥锁。"""

    def __init__(self) -> None:
        self._locks: dict[Path, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def get_lock(self, path: Path) -> asyncio.Lock:
        """获取指定文件路径对应的 asyncio.Lock（规范化绝对路径）。"""
        canonical = path.resolve()
        async with self._guard:
            if canonical not in self._locks:
                self._locks[canonical] = asyncio.Lock()
            return self._locks[canonical]

    def clear(self) -> None:
        """清空锁字典。"""
        self._locks.clear()
