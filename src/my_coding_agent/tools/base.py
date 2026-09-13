from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from my_agent_core.tools import ToolResult  # pyright: ignore[reportMissingImports]

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024  # 50KB
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


def resolve_path(workspace: Path, p: str | Path) -> Path:
    raw = Path(p)
    if raw.is_absolute():
        return raw.resolve()
    return (workspace / raw).resolve()


def is_binary_file(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except Exception:
        return False


@dataclass
class StringCompatibleToolResult(ToolResult):
    """ToolResult 子类：提供字符串兼容比较、包含、转换操作。

    共享基类，供 read/write/edit/bash/grep/find 工具继承，避免重复实现。
    """

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            val = self.data if self.data is not None else self.error
            return str(val) == other
        return super().__eq__(other)

    def __contains__(self, item: Any) -> bool:
        content = self.data if self.data is not None else (self.error or "")
        return str(item) in str(content)

    def __str__(self) -> str:
        return str(self.data if self.data is not None else self.error)

    def __repr__(self) -> str:
        return repr(self.data if self.data is not None else self.error)
