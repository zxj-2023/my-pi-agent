# pyright: reportUnusedCallResult=false, reportAttributeAccessIssue=false
"""Session 管理：树结构会话 + JSONL 文件持久化（纯正 Tau 只追加多态体系，配 my-agent-llm Message）。

一个会话 = 一棵树（entry 带 id/parent_id）+ current_id 指针。rewind = 移动指针、
旧分支保留。文件格式为纯粹的 SessionEntry 流：第 1 行是 SessionInfoEntry，后续每行为 MessageEntry/CompactionEntry 等。
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from my_agent_llm import Message

from .entries import (
    CompactionEntry,
    MessageEntry,
    SessionEntry,
    SessionInfoEntry,
)
from .jsonl import entry_from_json_line, entry_to_json_line
from .tree import path_to_entry


class SessionTree:
    """树：entries（id→entry）+ current_id 指针 + root_id。"""

    def __init__(self) -> None:
        self.entries: dict[str, SessionEntry] = {}
        self.current_id: str | None = None
        self.root_id: str | None = None

    def add_entry(self, role: str, content: str, parent_id: str | None = None, **metadata: Any) -> MessageEntry:
        """追加到 current 下（或指定 parent）。首个 entry 成为根。"""
        if parent_id is None:
            parent_id = self.current_id
        entry = MessageEntry(
            id=uuid4().hex[:8],
            parent_id=parent_id,
            message=Message(
                role=cast(Any, role),
                content=content,
                metadata=metadata or None,
            ),
        )
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
        try:
            return path_to_entry(self.entries, entry_id)
        except Exception as exc:
            raise ValueError(str(exc)) from exc

    def rewind(self, entry_id: str) -> None:
        """移动 current 指针到已有节点；新 entry 将在其下追加（长新枝）。不存在抛 ValueError。"""
        if entry_id not in self.entries:
            raise ValueError(f"Entry {entry_id} not found")
        self.current_id = entry_id

    @classmethod
    def from_jsonl_iter(cls, lines: Iterable[str]) -> SessionTree:
        """从迭代器恢复树。中途某行损坏抛 ValueError（带行号），尾行由 load 处理。"""
        tree = cls()
        for idx, line in enumerate(lines, start=2):  # start=2 因为 line 1 是 session_info
            line = line.strip()
            if not line:
                continue
            try:
                entry = entry_from_json_line(line)
            except Exception as exc:
                raise ValueError(f"Corrupted entry at line {idx}: {exc}") from exc
            tree.entries[entry.id] = entry
            tree.current_id = entry.id
            if tree.root_id is None:
                tree.root_id = entry.id
        return tree


class Session:
    """一个会话 = 树 + 路径 + JSONL 文件（纯正 Tau 多态 SessionEntry 流）。

    文件第 1 行是 SessionInfoEntry，后续每行是一个多态 SessionEntry。
    """

    def __init__(self, *, path: Path, cwd: str | None = None, metadata: dict | None = None):
        """新建会话（纯对话，不含 system）。不立即写文件。"""
        self.path = Path(path)
        self.id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        self.created_at = datetime.now().isoformat()
        self.cwd = cwd or str(Path.cwd())
        self.tree = SessionTree()
        self.compaction_floor: str | None = None
        self.metadata = metadata or {}  # 额外元数据（子代理：agent_type/parent_session_id），进 SessionInfoEntry
        self._storage: Any | None = None

    @classmethod
    def load(cls, path: Path) -> Session:
        """从 JSONL 文件恢复整棵树。首行非 SessionInfoEntry → ValueError；
        非尾行损坏 → ValueError（带行号）；尾行撕裂 → 丢弃该行（宽容兜底）。"""
        path = Path(path).resolve()
        try:
            with open(path, encoding="utf-8") as f:
                lines = list(f)
        except OSError as exc:
            raise ValueError(f"Failed to read session file {path}: {exc}") from exc
        if not lines:
            raise ValueError(f"Session file {path} is empty")

        try:
            first_entry = entry_from_json_line(lines[0])
        except Exception as exc:
            raise ValueError(f"Session file {path}: invalid header/info: {exc}") from exc

        if not isinstance(first_entry, SessionInfoEntry):
            raise ValueError(f"Session file {path}: line 1 must be a valid SessionInfoEntry")

        tree_lines = lines[1:]
        if tree_lines and tree_lines[-1].strip():
            try:
                entry_from_json_line(tree_lines[-1])
            except Exception:
                tree_lines = tree_lines[:-1]

        tree = SessionTree.from_jsonl_iter(tree_lines)
        meta = dict(first_entry.metadata)
        if getattr(first_entry, "name", None):
            meta["name"] = first_entry.name
        if getattr(first_entry, "title", None):
            meta["title"] = first_entry.title
        for e in tree.entries.values():
            if isinstance(e, SessionInfoEntry):
                sub_name = getattr(e, "name", None) or getattr(e, "title", None)
                if sub_name:
                    meta["name"] = sub_name
                    meta["title"] = sub_name

        # 优先恢复 current_id / root_id
        cur = meta.get("current_id")
        if isinstance(cur, str) and cur in tree.entries:
            tree.current_id = cur
        root = meta.get("root_id")
        if isinstance(root, str) and root in tree.entries:
            tree.root_id = root

        session = cls(path=path, cwd=first_entry.cwd)
        session.id = first_entry.id
        session.created_at = (
            datetime.fromtimestamp(first_entry.created_at).isoformat()
            if first_entry.created_at
            else datetime.now().isoformat()
        )
        session.tree = tree
        session.compaction_floor = meta.get("compaction_floor")
        session.metadata = {k: v for k, v in meta.items() if k not in ("current_id", "root_id", "compaction_floor")}
        return session

    def add_message(self, role: str, content: str, parent_id: str | None = None, **metadata: Any) -> MessageEntry:
        """加到树 + save()。"""
        entry = self.tree.add_entry(role, content, parent_id, **metadata)
        self.save()
        return entry

    def get_current_path_messages(self) -> list[Message]:
        """当前路径 → list[Message]（Agent 上下文用）。"""
        return [
            e.message
            if isinstance(e, MessageEntry)
            else Message(
                role=cast(Any, getattr(e, "role", "system")),
                content=getattr(e, "content", ""),
                metadata=getattr(e, "metadata", None),
            )
            for e in self.tree.get_current_path()
        ]

    def add_summary_cache(
        self,
        summary: str,
        *,
        covered_count: int,
        retained_tail: list[dict],
        tokens_before: int,
        summary_usage: dict | None = None,
        summary_model: str | None = None,
    ) -> None:
        """写一条 CompactionEntry（不动 current_id）+ 更新 compaction_floor。"""
        metadata: dict[str, Any] = {
            "retained_tail": retained_tail,
            "covered_count": covered_count,
            "tokens_before": tokens_before,
        }
        if summary_usage is not None:
            metadata["summary_usage"] = summary_usage
        if summary_model is not None:
            metadata["summary_model"] = summary_model
        entry = CompactionEntry(
            parent_id=self.tree.current_id,
            summary=summary,
            replaces_entry_ids=[],
            metadata=metadata,
        )
        self.tree.entries[entry.id] = entry
        self.compaction_floor = self.tree.current_id
        self.save()

    def get_full_history_messages(self) -> list[Message]:
        """完整对话历史（排除 CompactionEntry 节点）——宿主看历史、Agent 恢复上下文用。"""
        return [
            e.message
            if isinstance(e, MessageEntry)
            else Message(
                role=cast(Any, getattr(e, "role", "system")),
                content=getattr(e, "content", ""),
                metadata=getattr(e, "metadata", None),
            )
            for e in self.tree.get_current_path()
            if getattr(e, "type", "message") == "message"
        ]

    def get_latest_compaction_cache(self) -> dict | None:
        """最新一条 CompactionEntry → {summary, covered_count, retained_tail}；无则 None。"""
        cache_entries = [
            e
            for e in self.tree.entries.values()
            if isinstance(e, CompactionEntry) or getattr(e, "type", None) == "compaction"
        ]
        if not cache_entries:
            return None
        latest = max(cache_entries, key=lambda e: len(self.tree.get_path_to_entry(e.id)))
        md = getattr(latest, "metadata", {}) or {}
        try:
            covered_count = int(md.get("covered_count", 0))
        except (ValueError, TypeError):
            covered_count = 0
        return {
            "summary": getattr(latest, "summary", getattr(latest, "content", "")),
            "covered_count": covered_count,
            "retained_tail": list(md.get("retained_tail", [])),
        }

    def rewind(self, entry_id: str) -> None:
        """移动 current 指针（旧分支保留）+ save。压缩后只能回 floor（含）之后，否则 ValueError。"""
        if self.compaction_floor is not None and not self._after_floor(entry_id):
            raise ValueError(
                f"Cannot rewind past compaction floor {self.compaction_floor}: "
                f"entry {entry_id} is prior to compacted history"
            )
        self.tree.rewind(entry_id)
        self.save()

    def _after_floor(self, entry_id: str) -> bool:
        """entry_id 是否在 compaction_floor（含）之后长出的节点：等于 floor，或沿 parent 链能走到 floor。"""
        if entry_id == self.compaction_floor:
            return True
        cur = self.tree.entries.get(entry_id)
        while cur is not None and cur.parent_id is not None:
            if cur.parent_id == self.compaction_floor:
                return True
            cur = self.tree.entries.get(cur.parent_id)
        return False

    def save(self) -> None:
        """原子落盘：临时文件 + fsync + os.replace。写入首条 SessionInfoEntry 与所有多态 SessionEntry。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        meta = dict(self.metadata)
        meta["current_id"] = self.tree.current_id
        meta["root_id"] = self.tree.root_id
        meta["compaction_floor"] = self.compaction_floor

        created_at_val: float | None = None
        try:
            if isinstance(self.created_at, str):
                created_at_val = datetime.fromisoformat(self.created_at).timestamp()
            elif isinstance(self.created_at, (int, float)):
                created_at_val = float(self.created_at)
        except Exception:
            created_at_val = None

        name_val = meta.get("name") or meta.get("title")
        info_entry = SessionInfoEntry(
            id=self.id,
            cwd=self.cwd,
            title=name_val,
            name=name_val,
            created_at=created_at_val,
            metadata=meta,
        )

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
                f.write(entry_to_json_line(info_entry) + "\n")
                for e in self.tree.entries.values():
                    f.write(entry_to_json_line(e) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise

    def append_entry(self, entry: SessionEntry) -> None:
        """追加一条任意多态 SessionEntry 并原子持久化。"""
        if isinstance(entry, SessionInfoEntry):
            name_val = getattr(entry, "name", None) or getattr(entry, "title", None)
            if name_val:
                self.metadata["name"] = name_val
                self.metadata["title"] = name_val
            if entry.cwd:
                self.cwd = entry.cwd
        self.tree.entries[entry.id] = entry
        if self.tree.root_id is None:
            self.tree.root_id = entry.id
        self.tree.current_id = entry.id
        self.save()

    @property
    def store(self):
        """兼容层：暴露包含 append_entry 的 storage/store 接口。"""

        class _SessionStoreProxy:
            def __init__(self, session: Session):
                self._session = session

            def append_entry(self, entry: SessionEntry) -> None:
                self._session.append_entry(entry)

        return _SessionStoreProxy(self)

    def reset(self) -> None:
        """清空树 + 原子重写（纯对话，不含 system）。唯一破坏性操作。"""
        self.tree = SessionTree()
        self.compaction_floor = None
        self.save()

    def fork(self, entry_id: str, new_path: Path | None = None) -> Session:
        """从某 entry 分叉为新会话：复制根到 entry 的路径为新会话（新 id/路径，独立演化）。"""
        if entry_id not in self.tree.entries:
            raise ValueError(f"Entry {entry_id} not found")
        if new_path is None:
            sid = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
            new_path = self.path.parent / f"{sid}.jsonl"
        new_session = Session(path=new_path, cwd=self.cwd, metadata=dict(self.metadata))
        for entry in self.tree.get_path_to_entry(entry_id):
            if isinstance(entry, MessageEntry):
                new_session.add_message(entry.role, entry.content, **entry.metadata)
        return new_session

    @property
    def storage(self) -> Any:
        """底层只追加存储对象。"""
        if self._storage is None:
            from my_agent_core.session.storage import JsonlSessionStorage

            self._storage = JsonlSessionStorage(self.path)
        return self._storage

    def get_state(self) -> Any:
        """获取从根到当前 current_id 的 SessionState 状态快照。"""
        from my_agent_core.session.memory import SessionState

        return SessionState(
            messages=tuple(self.get_current_path_messages()),
            active_leaf_id=self.tree.current_id,
        )

    def get_history(self) -> list[Message]:
        """获取当前路径的对话历史列表。"""
        return self.get_current_path_messages()
