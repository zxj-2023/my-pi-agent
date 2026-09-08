"""Session package: entries, tree, state projection, and storage abstractions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    class Session:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        def __getattr__(self, name: str) -> Any: ...

    class SessionTree:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        def __getattr__(self, name: str) -> Any: ...

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
from .storage import (
    InMemorySessionStorage,
    SessionStorage,
)
from .tree import (
    SessionTreeError,
    entries_by_id,
    lowest_common_ancestor,
    path_to_entry,
)

# ---------------------------------------------------------------------------
# 向后兼容支持：在 Milestone 2 拆解期间，桥接原有 session.py 门面对象
# ---------------------------------------------------------------------------
_legacy_file = Path(__file__).parent.parent / "session.py"
if _legacy_file.exists():
    _spec = importlib.util.spec_from_file_location("_legacy_session", _legacy_file)
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["_legacy_session"] = _mod
        _spec.loader.exec_module(_mod)
        for _k, _v in _mod.__dict__.items():
            if not _k.startswith("__") and _k not in globals():
                globals()[_k] = _v

__all__ = [
    # Legacy exports
    "Session",
    "SessionTree",
    # New modular entries
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
