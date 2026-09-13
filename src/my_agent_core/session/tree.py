"""Pure in-memory DAG tree algorithms for session entries.

Provides entry mapping indexing with duplicate ID protection, cycle detection,
and path extraction from root to leaf, operating with zero I/O side-effects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .entries import SessionEntry


class SessionTreeError(ValueError):
    """Raised when an illegal operation or cycle occurs in the session DAG tree."""


def entries_by_id(entries: Sequence[SessionEntry]) -> dict[str, SessionEntry]:
    """建立 entry_id 到 SessionEntry 的索引字典。遇到重复 ID 抛出 SessionTreeError。"""
    by_id: dict[str, SessionEntry] = {}
    for entry in entries:
        if entry.id in by_id:
            raise SessionTreeError(f"Duplicate entry id: {entry.id}")
        by_id[entry.id] = entry
    return by_id


def path_to_entry(
    entries: Sequence[SessionEntry] | Mapping[str, SessionEntry],
    leaf_id: str,
) -> list[SessionEntry]:
    """从根节点回溯到 leaf_id 的有序路径条目列表（根节点在前，叶节点在后）。

    遇到缺失父节点报错，遇到循环引用抛出带 'Cycle detected' 的 SessionTreeError。
    """
    if isinstance(entries, Mapping):
        by_id = entries
    else:
        by_id = entries_by_id(entries)

    if leaf_id not in by_id:
        raise SessionTreeError(f"Entry {leaf_id} not found")

    path: list[SessionEntry] = []
    seen: set[str] = set()
    curr_id: str | None = leaf_id

    while curr_id is not None:
        if curr_id in seen:
            raise SessionTreeError(f"Cycle detected at entry {curr_id}")
        seen.add(curr_id)

        entry = by_id.get(curr_id)
        if entry is None:
            raise SessionTreeError(f"Missing parent entry: {curr_id}")

        path.append(entry)
        curr_id = entry.parent_id

    path.reverse()
    return path


def lowest_common_ancestor(
    entries: Sequence[SessionEntry] | Mapping[str, SessionEntry],
    id1: str,
    id2: str,
) -> str | None:
    """计算两个节点的最近公共祖先 (LCA) ID。若无公共祖先则返回 None。"""
    path1 = [e.id for e in path_to_entry(entries, id1)]
    path2 = [e.id for e in path_to_entry(entries, id2)]
    ancestor: str | None = None
    for a, b in zip(path1, path2, strict=False):
        if a == b:
            ancestor = a
        else:
            break
    return ancestor


__all__ = [
    "SessionTreeError",
    "entries_by_id",
    "path_to_entry",
    "lowest_common_ancestor",
]
