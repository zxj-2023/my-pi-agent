from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from my_agent_core.tools import (
    DEFAULT_TOOL_MAX_BYTES,
    DEFAULT_TOOL_MAX_LINES,
    Tool,
    ToolResult,
    truncate_tool_output,
)

DEFAULT_MAX_LINES = DEFAULT_TOOL_MAX_LINES
DEFAULT_MAX_BYTES = DEFAULT_TOOL_MAX_BYTES
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}
PATH_ALIASES: tuple[str, ...] = ("filePath", "file_path", "file", "filename")


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


def truncate_output(
    text: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_lines: int = DEFAULT_MAX_LINES,
) -> str:
    """按行与字节双重限制截断输出并对齐（对标 Pi 规范：50KB 或 2000行）。"""
    return truncate_tool_output(text, max_bytes=max_bytes, max_lines=max_lines)


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


def wrap_tool_executor(
    target_tool: Tool,
    aliases: dict[str, tuple[str, ...]] | None = None,
    normalizer: Callable[[dict[str, Any]], None] | None = None,
) -> Tool:
    """统一为工作区工具包装参数别名映射与 StringCompatibleToolResult 返回值。"""
    orig_execute = target_tool.execute

    async def execute(
        args: dict[str, Any] | None = None,
        signal: Any | None = None,
        on_update: Callable[[Any], None] | None = None,
        tool_call_id: str | None = None,
        **kwargs: Any,
    ) -> StringCompatibleToolResult:
        call_args = dict(args) if isinstance(args, dict) else {}
        call_args.update(kwargs)
        if aliases:
            for canonical, alias_keys in aliases.items():
                if canonical not in call_args:
                    for k in alias_keys:
                        if k in call_args:
                            call_args[canonical] = call_args.pop(k)
                            break
        if normalizer:
            normalizer(call_args)
        res = await orig_execute(
            call_args,
            signal=signal,
            on_update=on_update,
            tool_call_id=tool_call_id,
        )
        if isinstance(res, StringCompatibleToolResult):
            return res
        if isinstance(getattr(res, "data", None), StringCompatibleToolResult):
            return res.data
        return StringCompatibleToolResult(
            ok=res.ok,
            data=res.data,
            error=res.error,
            meta=res.meta,
            terminate=res.terminate,
        )

    target_tool.execute = execute
    return target_tool
