"""MemoryStore - 条目化长期记忆存储与 System Prompt 冻结快照管理。

采用 Markdown 文件（MEMORY.md / USER.md）持久化存储，支持 `\\n§\\n` 条目分隔、
utf-8-sig 编码容错、唯原子串定位增删改、字符上限约束与原子落盘。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

ENTRY_DELIMITER = "\n§\n"
MEMORY_CHAR_LIMIT = 2200
USER_CHAR_LIMIT = 1375

TargetType = Literal["memory", "user"]


class MemoryStore:
    """管理 MEMORY.md 与 USER.md 的持久化记忆存储仓储（支持 Frozen Snapshot 与原子落盘）。"""

    def __init__(
        self,
        mem_dir: Path | str,
        memory_char_limit: int = MEMORY_CHAR_LIMIT,
        user_char_limit: int = USER_CHAR_LIMIT,
    ) -> None:
        self.mem_dir = Path(mem_dir)
        self.limits: dict[str, int] = {
            "memory": memory_char_limit,
            "user": user_char_limit,
        }
        self.files: dict[str, str] = {
            "memory": "MEMORY.md",
            "user": "USER.md",
        }
        self._entries: dict[str, list[str]] = {"memory": [], "user": []}
        self._snapshot: dict[str, str] = {"memory": "", "user": ""}

    def load_from_disk(self) -> None:
        """从磁盘读取 MEMORY.md 和 USER.md，解析并冻结 System Prompt 快照。"""
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        for target, filename in self.files.items():
            path = self.mem_dir / filename
            entries: list[str] = []
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8-sig").strip()
                    if content:
                        raw_parts = [p.strip() for p in content.split(ENTRY_DELIMITER)]
                        # 去重且保持插入顺序
                        entries = list(dict.fromkeys(p for p in raw_parts if p))
                except Exception:
                    entries = []
            self._entries[target] = entries
            self._snapshot[target] = ENTRY_DELIMITER.join(entries) if entries else ""

    def _atomic_save(self, target: str) -> None:
        """将指定 target 的 entries 原子写入对应文件。"""
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        path = self.mem_dir / self.files[target]
        text = ENTRY_DELIMITER.join(self._entries[target])
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".{self.files[target]}.", dir=str(self.mem_dir)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8-sig") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def add(self, target: str, content: str) -> str:
        """追加一条记忆条目并落盘。"""
        if target not in self.files:
            return f"Invalid target '{target}'. Must be 'memory' or 'user'."
        text = content.strip()
        if not text:
            return "Content cannot be empty."

        entries = self._entries[target]
        if text in entries:
            return f"Entry already exists in {target}."

        candidate = entries + [text]
        full_text = ENTRY_DELIMITER.join(candidate)
        limit = self.limits[target]
        if len(full_text) > limit:
            current_dump = "\n---\n".join(entries) if entries else "(empty)"
            return (
                f"Cannot add: total length ({len(full_text)}) exceeds limit ({limit}) for {target}.\n"
                f"Please consolidate or remove older entries first.\n"
                f"Current entries:\n{current_dump}"
            )

        self._entries[target] = candidate
        self._atomic_save(target)
        return f"Added to {target} ({len(full_text)}/{limit} chars used)."

    def replace(self, target: str, old_text: str, new_content: str) -> str:
        """根据 old_text 唯原子串匹配定位替换条目。"""
        if target not in self.files:
            return f"Invalid target '{target}'. Must be 'memory' or 'user'."
        old_needle = old_text.strip()
        if not old_needle:
            return "old_text cannot be empty."
        new_text = new_content.strip()
        if not new_text:
            return "new_content cannot be empty."

        entries = self._entries[target]
        matches = [i for i, entry in enumerate(entries) if old_needle in entry]

        if not matches:
            return f"Text '{old_needle}' not found in {target}."
        if len(matches) > 1:
            matching_texts = "\n---\n".join(entries[i] for i in matches)
            return (
                f"Ambiguous match: found {len(matches)} entries matching '{old_needle}' in {target}.\n"
                f"Please provide a more specific old_text.\nMatching entries:\n{matching_texts}"
            )

        idx = matches[0]
        candidate = list(entries)
        candidate[idx] = new_text

        full_text = ENTRY_DELIMITER.join(candidate)
        limit = self.limits[target]
        if len(full_text) > limit:
            return (
                f"Cannot replace: total length ({len(full_text)}) exceeds limit ({limit}) for {target}.\n"
                f"Please consolidate or shorten entries."
            )

        self._entries[target] = candidate
        self._atomic_save(target)
        return f"Replaced in {target} ({len(full_text)}/{limit} chars used)."

    def remove(self, target: str, old_text: str) -> str:
        """根据 old_text 唯原子串匹配定位删除条目。"""
        if target not in self.files:
            return f"Invalid target '{target}'. Must be 'memory' or 'user'."
        old_needle = old_text.strip()
        if not old_needle:
            return "old_text cannot be empty."

        entries = self._entries[target]
        matches = [i for i, entry in enumerate(entries) if old_needle in entry]

        if not matches:
            return f"Text '{old_needle}' not found in {target}."
        if len(matches) > 1:
            matching_texts = "\n---\n".join(entries[i] for i in matches)
            return (
                f"Ambiguous match: found {len(matches)} entries matching '{old_needle}' in {target}.\n"
                f"Please provide a more specific old_text.\nMatching entries:\n{matching_texts}"
            )

        idx = matches[0]
        candidate = [e for i, e in enumerate(entries) if i != idx]
        self._entries[target] = candidate
        self._atomic_save(target)
        limit = self.limits[target]
        curr_len = len(ENTRY_DELIMITER.join(candidate)) if candidate else 0
        return f"Removed from {target} ({curr_len}/{limit} chars used)."

    def format_for_system_prompt(self, target: str) -> str | None:
        """获取冻结的快照字符串（返回 None 代表无内容）。"""
        snapshot = self._snapshot.get(target, "")
        return snapshot if snapshot else None

    def format_all_for_system_prompt(self) -> str | None:
        """将冻结的快照格式化为注入 System Prompt 的 XML 块。"""
        blocks = []
        mem = self.format_for_system_prompt("memory")
        if mem:
            blocks.append(f"## MEMORY.md (Agent Notes)\n{mem}")
        usr = self.format_for_system_prompt("user")
        if usr:
            blocks.append(f"## USER.md (User Profile)\n{usr}")

        if not blocks:
            return None
        joined = "\n\n".join(blocks)
        return (
            "<MEMORY_CONTEXT>\n"
            "The following is your long-term memory across sessions. "
            "Use the `memory` tool to update it when learning new facts or preferences.\n\n"
            f"{joined}\n"
            "</MEMORY_CONTEXT>"
        )
