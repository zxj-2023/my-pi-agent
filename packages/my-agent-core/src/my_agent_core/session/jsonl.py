"""JSONL append-only session storage implementation with cross-process locking and recovery."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import time
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from my_agent_llm.models import Message
from pydantic import BaseModel, TypeAdapter

from .entries import (
    CompactionEntry,
    MessageEntry,
    SessionEntry,
    SessionInfoEntry,
)

# 跨平台文件锁底层调用
if sys.platform == "win32":
    import msvcrt

    def _lock_file_sync(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock_file_sync(fd: int) -> None:
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_file_sync(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_file_sync(fd: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)


class SessionJsonlError(ValueError):
    """JSONL 序列化、反序列化、文件损坏或锁获取异常。"""


_ENTRY_ADAPTER: TypeAdapter[SessionEntry] = TypeAdapter(SessionEntry)


def entry_to_json_line(entry: SessionEntry) -> str:
    """将 SessionEntry 序列化为单行 JSON 字符串（不带尾随换行符）。"""
    try:
        if isinstance(entry, BaseModel):
            return entry.model_dump_json(by_alias=True, exclude_none=True)
        return _ENTRY_ADAPTER.dump_json(entry, by_alias=True, exclude_none=True).decode(
            "utf-8"
        )
    except Exception as exc:
        raise SessionJsonlError(
            f"Failed to serialize entry to JSON line: {exc}"
        ) from exc


def _parse_timestamp(raw: Any) -> float:
    """安全解析时间戳，支持 ISO 格式字符串与浮点数/整数。"""
    if raw is None:
        return time.time()
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw).timestamp()
        except Exception:
            try:
                return float(raw)
            except Exception:
                return time.time()
    return time.time()


def _migrate_session_entry(raw: dict[str, Any]) -> SessionEntry:
    """兼容旧版文件头与遗留条目格式，迁移并返回强类型 SessionEntry。"""
    data = dict(raw)
    entry_type = data.get("type")

    # 1. 遗留文件头 (Header) 检查
    is_legacy_header = (entry_type == "session") or (
        entry_type is None
        and "role" not in data
        and (
            "created_at" in data
            or "cwd" in data
            or "current_id" in data
            or "root_id" in data
        )
    )
    if is_legacy_header:
        entry_id = str(data.get("id") or uuid4().hex)
        cwd = data.get("cwd")
        title = data.get("title")
        created_at_raw = data.get("created_at")
        created_at_float: float | None = None
        if created_at_raw is not None:
            try:
                created_at_float = (
                    datetime.fromisoformat(created_at_raw).timestamp()
                    if isinstance(created_at_raw, str)
                    else float(created_at_raw)
                )
            except Exception:
                created_at_float = None
        timestamp_float = created_at_float or time.time()
        meta = dict(data.get("metadata") or {})
        for k in ("current_id", "root_id", "compaction_floor", "version"):
            if k in data and data[k] is not None:
                meta[k] = data[k]
        return SessionInfoEntry(
            id=entry_id,
            cwd=cwd,
            title=title,
            created_at=created_at_float,
            timestamp=timestamp_float,
            metadata=meta,
        )

    # 2. 遗留压缩条目检查 (type == 'compaction', summary in 'content')
    if entry_type == "compaction" and "summary" not in data and "content" in data:
        entry_id = str(data.get("id") or uuid4().hex)
        parent_id = data.get("parent_id") or data.get("parentId")
        ts_float = _parse_timestamp(data.get("timestamp"))
        summary = str(data["content"])
        replaces = list(
            data.get("replaces_entry_ids") or data.get("replacesEntryIds") or []
        )
        meta = dict(data.get("metadata") or {})
        return CompactionEntry(
            id=entry_id,
            parent_id=parent_id,
            timestamp=ts_float,
            summary=summary,
            replaces_entry_ids=replaces,
            metadata=meta,
        )

    # 3. 遗留对话消息条目检查 (role at top level, no nested 'message')
    is_legacy_message = (
        "role" in data and "message" not in data and entry_type in ("message", None)
    )
    if is_legacy_message:
        entry_id = str(data.get("id") or uuid4().hex)
        parent_id = data.get("parent_id") or data.get("parentId")
        ts_float = _parse_timestamp(data.get("timestamp"))
        role = str(data["role"])
        content = str(data.get("content", ""))
        meta = dict(data.get("metadata") or {})
        msg = Message(role=cast(Any, role), content=content, metadata=meta or None)
        return MessageEntry(
            id=entry_id,
            parent_id=parent_id,
            timestamp=ts_float,
            message=msg,
        )

    # 4. 当前 9 种 SessionEntry 多态反序列化
    try:
        return _ENTRY_ADAPTER.validate_python(data)
    except Exception as exc:
        raise SessionJsonlError(
            f"Cannot parse JSON object as SessionEntry: {exc}"
        ) from exc


def entry_from_json_line(line: str) -> SessionEntry:
    """从单行 JSON 字符串解析 SessionEntry，自动处理遗留迁移。"""
    stripped = line.strip()
    if not stripped:
        raise SessionJsonlError("JSONL line is empty or blank")

    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise SessionJsonlError(f"Invalid JSON line: {exc}") from exc

    if not isinstance(raw, dict):
        raise SessionJsonlError(f"Expected JSON object, got {type(raw).__name__}")

    return _migrate_session_entry(raw)


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
                    _lock_file_sync(fd)
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
                _unlock_file_sync(fd)
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
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

    async def append_batch(self, entries: Sequence[SessionEntry]) -> None:
        """原子追加一批条目到存储末尾。"""
        if not entries:
            return
        async with self._lock():
            self._remove_incomplete_temp()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lines = [entry_to_json_line(e) for e in entries]
            with open(self.path, "a", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

    async def read_all(self) -> list[SessionEntry]:
        """读取存储中所有按追加时序排列的历史条目。"""
        async with self._lock():
            self._remove_incomplete_temp()
            if not self.path.exists():
                return []

            with open(self.path, encoding="utf-8") as f:
                raw_lines = f.readlines()

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
                    if is_last and len(entries) > 0:
                        break
                    raise exc
            return entries


__all__ = [
    "SessionJsonlError",
    "entry_to_json_line",
    "entry_from_json_line",
    "JsonlSessionStorage",
]
