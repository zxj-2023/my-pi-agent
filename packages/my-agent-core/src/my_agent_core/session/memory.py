"""Pure in-memory state fold projection for session entries.

Provides the immutable SessionState dataclass and pure function folding over
path entries from root to leaf, applying model changes, thinking levels,
labels, leaf pointers, and compaction history replacements.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from my_agent_llm.models import Message

from .entries import (
    CompactionEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionEntry,
    ThinkingLevelChangeEntry,
)
from .tree import path_to_entry


def _apply_compaction(
    items: list[tuple[str, Message]],
    entry: CompactionEntry,
) -> list[tuple[str, Message]]:
    """将 replaces_entry_ids 范围内的消息条目折叠为一条 UserMessage 摘要。"""
    summary_text = entry.summary
    prefix = "Previous conversation summary:\n"
    if summary_text.startswith(prefix):
        content = summary_text
    else:
        content = f"{prefix}{summary_text}"

    summary_msg = Message(role="user", content=content)
    replaces_set = set(entry.replaces_entry_ids)

    if not replaces_set:
        return [*items, (entry.id, summary_msg)]

    new_items: list[tuple[str, Message]] = []
    inserted = False
    for eid, msg in items:
        if eid in replaces_set:
            if not inserted:
                new_items.append((entry.id, summary_msg))
                inserted = True
        else:
            new_items.append((eid, msg))

    if not inserted:
        new_items.append((entry.id, summary_msg))

    return new_items


@dataclass(frozen=True, slots=True)
class SessionState:
    """不可变运行时会话状态快照。

    通过事件溯源沿树状 DAG 路径纯函数折叠聚合生成，无锁且线程安全。
    """

    messages: tuple[Message, ...] = ()
    model: str | None = None
    provider: str | None = None
    thinking_level: str | None = None
    label: str | None = None
    active_leaf_id: str | None = None

    @classmethod
    def from_entries(
        cls,
        entries: Sequence[SessionEntry],
        leaf_id: str | None = None,
    ) -> SessionState:
        """纯函数折叠投影：沿根至 leaf_id 的路径条目无锁计算出最新运行时状态。"""
        if not entries:
            return cls()

        # 确定目标叶节点 ID
        if leaf_id is not None:
            target_leaf_id = leaf_id
        else:
            # 若存在 LeafEntry 指针，取最后一条 LeafEntry 指定的叶节点
            target_leaf_id = None
            for entry in reversed(entries):
                if isinstance(entry, LeafEntry):
                    target_leaf_id = entry.leaf_id
                    break
            if target_leaf_id is None:
                target_leaf_id = entries[-1].id

        # 提取从根至目标叶节点的有序单链路径
        path = path_to_entry(entries, target_leaf_id)

        # 沿路径纯函数折叠投影
        items: list[tuple[str, Message]] = []
        model: str | None = None
        provider: str | None = None
        thinking_level: str | None = None
        label: str | None = None
        active_leaf_id: str | None = target_leaf_id

        for entry in path:
            if isinstance(entry, MessageEntry):
                items.append((entry.id, entry.message))
            elif isinstance(entry, CompactionEntry):
                items = _apply_compaction(items, entry)
            elif isinstance(entry, ModelChangeEntry):
                model = entry.model
                if entry.provider is not None:
                    provider = entry.provider
            elif isinstance(entry, ThinkingLevelChangeEntry):
                thinking_level = entry.thinking_level
            elif isinstance(entry, LabelEntry):
                label = entry.label
            elif isinstance(entry, LeafEntry):
                active_leaf_id = entry.leaf_id

        return cls(
            messages=tuple(msg for _, msg in items),
            model=model,
            provider=provider,
            thinking_level=thinking_level,
            label=label,
            active_leaf_id=active_leaf_id,
        )


__all__ = [
    "SessionState",
]
