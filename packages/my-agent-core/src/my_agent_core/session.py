"""Session 管理：树结构会话 + JSONL 文件持久化（pig-mono 式，配 my-agent-llm Message）。

一个会话 = 一棵树（entry 带 id/parent_id）+ current_id 指针。rewind = 移动指针、
旧分支保留。文件格式见 session 设计文档 §3：header 行 + 每行一个 entry。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable
from uuid import uuid4

from pydantic import BaseModel, Field


class SessionEntry(BaseModel):
    """树的一个节点：一条消息 + 树关系。"""

    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    parent_id: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    role: str  # system / user / assistant / tool
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionTree:
    """树：entries（id→entry）+ current_id 指针 + root_id。"""

    def __init__(self) -> None:
        self.entries: dict[str, SessionEntry] = {}
        self.current_id: str | None = None
        self.root_id: str | None = None

    def add_entry(
        self, role: str, content: str, parent_id: str | None = None, **metadata: Any
    ) -> SessionEntry:
        """追加到 current 下（或指定 parent）。首个 entry 成为根。"""
        if parent_id is None:
            parent_id = self.current_id
        entry = SessionEntry(parent_id=parent_id, role=role, content=content, metadata=metadata)
        self.entries[entry.id] = entry
        self.current_id = entry.id
        if self.root_id is None:
            self.root_id = entry.id
        return entry

    def get_current_path(self) -> list[SessionEntry]:
        """根 → current 的路径（Agent 上下文用）。空树返回 []。"""
        if self.current_id is None:
            return []
        path: list[SessionEntry] = []
        cur = self.entries.get(self.current_id)
        while cur is not None:
            path.insert(0, cur)
            cur = self.entries.get(cur.parent_id) if cur.parent_id else None
        return path

    def rewind(self, entry_id: str) -> None:
        """把 current 移到 entry_id（回退）。旧分支保留。"""
        if entry_id not in self.entries:
            raise ValueError(f"Entry {entry_id} not found")
        self.current_id = entry_id

    def to_jsonl(self) -> str:
        """整棵树 → JSONL 字符串（每行一个 entry）。"""
        return "\n".join(e.model_dump_json() for e in self.entries.values())

    @classmethod
    def from_jsonl_iter(cls, lines: Iterable[str]) -> "SessionTree":
        """从 entry 行重建树。任一行损坏抛 ValueError（带行号）。head 之后从 2 起算。"""
        tree = cls()
        for line_no, line in enumerate(lines, start=2):
            line = line.strip()
            if not line:
                continue
            try:
                entry = SessionEntry.model_validate_json(line)
            except Exception as exc:
                raise ValueError(f"Line {line_no}: invalid entry JSON: {exc}") from exc
            tree.entries[entry.id] = entry
            if tree.root_id is None and entry.parent_id is None:
                tree.root_id = entry.id
        return tree