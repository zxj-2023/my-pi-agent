"""JSONL format serialization, parsing, and error definitions for session entries.

对齐 Tau (tau_agent.session.jsonl) 架构设计：
本模块纯粹负责 SessionEntry 与单行 JSONL 文本之间的双向序列化与反序列化，
以及行格式异常定义。持久化驱动与文件锁已归位至 storage.py。
"""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from .entries import SessionEntry


class SessionJsonlError(ValueError):
    """JSONL 序列化、反序列化或格式损坏异常。"""


_ENTRY_ADAPTER: TypeAdapter[SessionEntry] = TypeAdapter(SessionEntry)


def entry_to_json_line(entry: SessionEntry) -> str:
    """将 SessionEntry 序列化为单行 JSON 字符串（不带尾随换行符）。"""
    try:
        return entry.model_dump_json(by_alias=True, exclude_none=True)
    except Exception as exc:
        raise SessionJsonlError(
            f"Failed to serialize entry to JSON line: {exc}"
        ) from exc


def entry_from_json_line(line: str) -> SessionEntry:
    """从单行 JSON 字符串解析 SessionEntry。"""
    stripped = line.strip()
    if not stripped:
        raise SessionJsonlError("JSONL line is empty or blank")

    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise SessionJsonlError(f"Invalid JSON line: {exc}") from exc

    if not isinstance(raw, dict):
        raise SessionJsonlError(f"Expected JSON object, got {type(raw).__name__}")

    try:
        return _ENTRY_ADAPTER.validate_python(raw)
    except Exception as exc:
        raise SessionJsonlError(
            f"Cannot parse JSON object as SessionEntry: {exc}"
        ) from exc


__all__ = [
    "SessionJsonlError",
    "entry_to_json_line",
    "entry_from_json_line",
]
