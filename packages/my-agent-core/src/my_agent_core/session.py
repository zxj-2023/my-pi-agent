"""Session 管理：树结构会话 + JSONL 文件持久化（pig-mono 式，配 my-agent-llm Message）。

一个会话 = 一棵树（entry 带 id/parent_id）+ current_id 指针。rewind = 移动指针、
旧分支保留。文件格式见 session 设计文档 §3：header 行 + 每行一个 entry。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from my_agent_llm import Message
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
        return self.get_path_to_entry(self.current_id)

    def get_path_to_entry(self, entry_id: str) -> list[SessionEntry]:
        """根 → entry_id 的路径（fork 用）。不存在抛 ValueError。"""
        if entry_id not in self.entries:
            raise ValueError(f"Entry {entry_id} not found")
        path: list[SessionEntry] = []
        cur = self.entries.get(entry_id)
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


class Session:
    """树 + 文件持久化（逐条原子全量重写）。"""

    def __init__(self, *, path: Path, cwd: str | None = None, system_prompt: str | None = None):
        """新建会话。system_prompt 非 None 时作为首个（根）entry 入树。不立即写文件。"""
        self.path = Path(path)
        self.id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        self.created_at = datetime.now().isoformat()
        self.cwd = cwd or str(Path.cwd())
        self.tree = SessionTree()
        if system_prompt is not None:
            self.tree.add_entry("system", system_prompt)

    @classmethod
    def load(cls, path: Path) -> "Session":
        """从 JSONL 文件恢复整棵树。header 缺失/非法/version 不支持 → ValueError；
        非尾行 JSON 损坏 → ValueError（带行号）；尾行撕裂 → 丢弃该行（宽容兜底）。"""
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f]
        if not lines:
            raise ValueError(f"Session file {path} is empty")
        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Session file {path}: invalid header: {exc}") from exc
        if header.get("type") != "session" or header.get("version") != 1:
            raise ValueError(
                f"Session file {path}: unsupported header "
                f"(type={header.get('type')!r}, version={header.get('version')!r})"
            )
        # 尾行撕裂：最后一行 JSON 损坏 → 丢弃
        tree_lines = lines[1:]
        if tree_lines and tree_lines[-1].strip():
            try:
                SessionEntry.model_validate_json(tree_lines[-1])
            except Exception:
                tree_lines = tree_lines[:-1]
        tree = SessionTree.from_jsonl_iter(tree_lines)
        # header 优先恢复 current/root（文件为准，决策 5）
        cur = header.get("current_id")
        if isinstance(cur, str) and cur in tree.entries:
            tree.current_id = cur
        root = header.get("root_id")
        if isinstance(root, str) and root in tree.entries:
            tree.root_id = root
        session = cls(path=path, cwd=header.get("cwd"))
        session.id = header["id"]
        session.created_at = header["created_at"]
        session.tree = tree
        return session

    def add_message(
        self, role: str, content: str, parent_id: str | None = None, **metadata: Any
    ) -> SessionEntry:
        """加到树 + save()（逐条原子全量重写）。"""
        entry = self.tree.add_entry(role, content, parent_id, **metadata)
        self.save()
        return entry

    def rewind(self, entry_id: str) -> None:
        """移动 current 指针（旧分支保留）+ save。"""
        self.tree.rewind(entry_id)
        self.save()

    def get_current_path_messages(self) -> list[Message]:
        """当前路径 → list[Message]（Agent 上下文用）。"""
        return [
            Message(
                role=e.role,
                content=e.content,
                metadata=(dict(e.metadata) if e.metadata else None),
            )
            for e in self.tree.get_current_path()
        ]

    def save(self) -> None:
        """原子全量重写：临时文件 + fsync + os.replace。失败不破坏上次快照。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "type": "session",
            "version": 1,
            "id": self.id,
            "created_at": self.created_at,
            "cwd": self.cwd,
            "current_id": self.tree.current_id,
            "root_id": self.tree.root_id,
        }
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as f:
                temp_path = Path(f.name)
                f.write(json.dumps(header, ensure_ascii=False) + "\n")
                for e in self.tree.entries.values():
                    f.write(e.model_dump_json() + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise

    def reset(self) -> None:
        """清空树 + 原子重写（保留 system 消息）。唯一破坏性操作。"""
        system = [e for e in self.tree.entries.values() if e.role == "system"]
        self.tree = SessionTree()
        for e in system[:1]:
            self.tree.add_entry(e.role, e.content, **e.metadata)
        self.save()