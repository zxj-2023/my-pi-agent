"""Session package: entries, tree, state projection, storage abstractions, and Session manager."""

from __future__ import annotations

from .entries import (
    BaseSessionEntry,
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionEntry,
    SessionInfoEntry,
    ThinkingLevelChangeEntry,
)
from .jsonl import (
    JsonlSessionStorage,
    SessionJsonlError,
    entry_from_json_line,
    entry_to_json_line,
)
from .memory import (
    SessionState,
)
from .session import (
    LegacySessionEntry,
    Session,
    SessionTree,
)
from .storage import (
    InMemorySessionStorage,
    SessionStorage,
)
from .store import (
    SessionMeta,
    SessionStore,
)
from .tree import (
    SessionTreeError,
    entries_by_id,
    lowest_common_ancestor,
    path_to_entry,
)

__all__ = [
    # Session manager & tree
    "Session",
    "SessionTree",
    "LegacySessionEntry",
    "SessionStore",
    "SessionMeta",
    # Modular entries
    "BaseSessionEntry",
    "SessionInfoEntry",
    "MessageEntry",
    "ModelChangeEntry",
    "ThinkingLevelChangeEntry",
    "CompactionEntry",
    "BranchSummaryEntry",
    "LabelEntry",
    "LeafEntry",
    "CustomEntry",
    "SessionEntry",
    # Tree algorithms
    "SessionTreeError",
    "entries_by_id",
    "path_to_entry",
    "lowest_common_ancestor",
    # Memory projection
    "SessionState",
    # Storage protocol & driver
    "SessionStorage",
    "InMemorySessionStorage",
    "JsonlSessionStorage",
    "SessionJsonlError",
    "entry_to_json_line",
    "entry_from_json_line",
]
