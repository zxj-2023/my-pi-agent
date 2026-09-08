"""Session package: entries, tree, state projection, and storage abstractions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
]
