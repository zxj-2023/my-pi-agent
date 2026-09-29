"""内核事件 → ACP ``session/update`` 通知的纯函数翻译层。

``my_agent_core`` 向外广播的是一等公民事实事件（``events.py`` 中的 frozen dataclass），
ACP 侧需要的是一串 ``session/update`` 通知。本模块只做单向、无状态的映射，
不持有任何会话状态，便于单独测试。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acp import (
    start_tool_call,
    text_block,
    tool_content,
    update_agent_message_text,
    update_agent_thought_text,
    update_tool_call,
)
from acp.schema import ToolCallLocation, ToolKind
from my_agent_core.events import (
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
)

__all__ = [
    "TOOL_KINDS",
    "TOOL_TITLES",
    "MAX_RESULT_CHARS",
    "tool_kind",
    "tool_title",
    "tool_locations",
    "translate_message_update",
    "translate_tool_start",
    "translate_tool_end",
]

#: 内置工具 → ACP 工具类别（决定编辑器侧的图标与 UI 处理方式）。
TOOL_KINDS: dict[str, ToolKind] = {
    "read": "read",
    "write": "edit",
    "edit": "edit",
    "bash": "execute",
    "grep": "search",
    "find": "search",
    "ls": "read",
}

#: 内置工具 → 标题模板，``{key}`` 取自工具入参。
TOOL_TITLES: dict[str, str] = {
    "read": "Read {path}",
    "write": "Write {path}",
    "edit": "Edit {path}",
    "bash": "Run {command}",
    "grep": "Search {pattern}",
    "find": "Find {pattern}",
    "ls": "List {path}",
}

#: 工具结果回传给编辑器时的最大字符数，避免超大输出撑爆 JSON-RPC 帧。
MAX_RESULT_CHARS = 8000

#: 会被解析为文件位置的工具入参键。
_PATH_KEYS = ("path", "file_path", "filePath")


def tool_kind(tool_name: str) -> ToolKind:
    """把工具名映射为 ACP 工具类别，未知工具回落 ``other``。"""
    return TOOL_KINDS.get(tool_name, "other")


def tool_title(tool_name: str, args: dict[str, Any] | None) -> str:
    """构造人类可读的工具调用标题。"""
    args = args or {}
    template = TOOL_TITLES.get(tool_name)
    if template is None:
        return tool_name
    try:
        return template.format_map(_SafeFormatArgs(args))
    except Exception:  # pragma: no cover - 模板与入参不匹配时的兜底
        return tool_name


class _SafeFormatArgs(dict):
    """缺失键回落空串，避免工具入参不齐时格式化抛错。"""

    def __missing__(self, key: str) -> str:
        return ""


def tool_locations(tool_name: str, args: dict[str, Any] | None, workspace: Path) -> list[ToolCallLocation]:
    """从工具入参中提取文件位置，供编辑器跳转与 diff 高亮。"""
    args = args or {}
    raw = next((args[k] for k in _PATH_KEYS if args.get(k)), None)
    if not isinstance(raw, str) or not raw:
        return []
    try:
        resolved = Path(raw)
        if not resolved.is_absolute():
            resolved = workspace / resolved
        return [ToolCallLocation(path=str(resolved))]
    except (OSError, ValueError):
        return []


def translate_message_update(event: MessageUpdate) -> list[Any]:
    """把流式增量事件翻译为 0~1 条 ACP 更新。

    思考内容走 ``agent_thought_chunk``，正文走 ``agent_message_chunk``。
    工具调用增量（``chunk.tool_calls``）不在此翻译 —— 工具生命周期由
    ``ToolExecutionStart`` / ``ToolExecutionEnd`` 事件完整表达。
    """
    chunk = event.chunk
    if chunk is None:
        return []

    updates: list[Any] = []

    reasoning = getattr(chunk, "reasoning_content", None)
    if not reasoning and isinstance(getattr(chunk, "metadata", None), dict):
        reasoning = chunk.metadata.get("reasoning_content")
    if reasoning:
        updates.append(update_agent_thought_text(str(reasoning)))

    content = getattr(chunk, "content", None)
    if content:
        updates.append(update_agent_message_text(str(content)))

    return updates


def translate_tool_start(event: ToolExecutionStart, workspace: Path) -> Any:
    """把工具开始事件翻译为 ``tool_call`` 通知。"""
    return start_tool_call(
        event.tool_call_id,
        tool_title(event.tool_name, event.args),
        kind=tool_kind(event.tool_name),
        status="in_progress",
        locations=tool_locations(event.tool_name, event.args, workspace),
        raw_input=event.args or None,
    )


def translate_tool_end(event: ToolExecutionEnd, workspace: Path) -> Any:
    """把工具结束事件翻译为 ``tool_call_update`` 通知。"""
    result = event.result or ""
    if len(result) > MAX_RESULT_CHARS:
        result = result[:MAX_RESULT_CHARS] + f"\n… [truncated, {len(event.result)} chars total]"

    return update_tool_call(
        event.tool_call_id,
        status="failed" if event.is_error else "completed",
        content=[tool_content(text_block(result))] if result else None,
        raw_output=result or None,
    )
