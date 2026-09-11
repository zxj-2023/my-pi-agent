"""工具注册表 —— 持有工具集合，按名字查表与执行。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from my_agent_core.tools import Tool, ToolResult, tool

__all__ = ["Tool", "ToolRegistry", "ToolResult", "tool"]


class ToolRegistry:
    """工具注册表：持有工具集合，按名字查表与执行。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        """当前全部工具（发现顺序）。"""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """生成全部工具的 OpenAI tools 参数。"""
        return [t.to_openai_schema() for t in self._tools.values()]

    async def execute_tool(
        self,
        tool_call: Any = None,
        *,
        name: str | None = None,
        args: dict[str, Any] | str | None = None,
    ) -> ToolResult:
        """执行单个 tool 调用。

        支持多种入参形式：
        1. 原生结构化传参: execute_tool(name="add", args={"a": 1})
        2. 元组传参: execute_tool(("add", {"a": 1}))
        3. 实体传参: execute_tool(ToolCall(id=..., name="add", args={"a": 1}))
        4. 字典传参: execute_tool({"name": "add", "args": {"a": 1}})
        5. 协议传参: execute_tool({"function": {"name": "add", "arguments": "..."}})
        任何错误都转成 ToolResult，永不抛。
        """
        target_name = name
        target_args = args

        if target_name is None:
            if isinstance(tool_call, tuple) and len(tool_call) == 2:
                target_name, target_args = str(tool_call[0]), tool_call[1]
            elif isinstance(tool_call, dict):
                if "function" in tool_call:
                    fn = tool_call.get("function") or {}
                    target_name = fn.get("name", "")
                    target_args = fn.get("arguments", "{}")
                else:
                    target_name = tool_call.get("name", "")
                    target_args = tool_call.get("args", {})
            elif isinstance(tool_call, str):
                target_name = tool_call
            elif tool_call is not None:
                target_name = getattr(tool_call, "name", "")  # pyright: ignore[reportAttributeAccessIssue]
                target_args = getattr(tool_call, "args", {})  # pyright: ignore[reportAttributeAccessIssue]

        final_args: dict[str, Any]
        if isinstance(target_args, str):
            try:
                parsed = json.loads(target_args) if target_args.strip() else {}
                if not isinstance(parsed, dict):
                    return ToolResult(
                        ok=False,
                        error=f"Invalid JSON arguments for tool '{target_name}': expected object dict",
                    )
                final_args = parsed
            except (json.JSONDecodeError, TypeError) as exc:
                return ToolResult(
                    ok=False,
                    error=f"Invalid JSON arguments for tool '{target_name}': {exc}",
                )
        elif isinstance(target_args, dict):
            final_args = target_args
        elif target_args is None:
            final_args = {}
        else:
            return ToolResult(
                ok=False,
                error=f"Invalid arguments for tool '{target_name}': expected dict, got {type(target_args).__name__}",
            )

        target = self._tools.get(target_name or "")
        if target is None:
            available = ", ".join(sorted(self._tools))
            return ToolResult(
                ok=False, error=f"Unknown tool '{target_name}'. Available: {available}"
            )
        return await target.execute(final_args)

    async def execute_batch(self, tool_calls: Sequence[Any]) -> list[ToolResult]:
        """批量执行工具调用（全员只读并发；只要包含一个写入则整批保序串行，防止因果时序倒置）。"""
        if not tool_calls:
            return []

        def _get_name(tc: Any) -> str:
            if isinstance(tc, tuple) and len(tc) == 2:
                return str(tc[0])
            if isinstance(tc, dict):
                if "function" in tc:
                    return str((tc.get("function") or {}).get("name", ""))
                return str(tc.get("name", ""))
            if tc is not None:
                name_attr = getattr(tc, "name", None)  # pyright: ignore[reportAttributeAccessIssue]
                if name_attr is not None:
                    return str(name_attr)
            return ""

        # 检查这批工具中是否包含任何不安全的写工具（或未知工具）
        has_sequential = any(
            (t := self._tools.get(_get_name(tc))) is None or not t.is_parallel_safe
            for tc in tool_calls
        )

        if has_sequential:
            # 只要包含一个写操作，整批严格按大模型输出的原始顺序串行执行，确保因果顺序绝对正确
            return [await self.execute_tool(tc) for tc in tool_calls]

        # 全部都是只读安全工具时，安全并发执行
        return list(await asyncio.gather(*(self.execute_tool(tc) for tc in tool_calls)))
