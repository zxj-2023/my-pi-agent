"""工具注册表 —— 持有工具集合，按名字查表与执行。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from my_agent_core.tools import Tool, ToolResult


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

    async def execute_tool_call(self, tool_call: dict) -> ToolResult:
        """执行单个 tool_call（收协议 dict）。任何错误都转成 ToolResult，永不抛。"""
        name = tool_call.get("function", {}).get("name", "")
        raw_args = tool_call.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError) as exc:
            return ToolResult(
                ok=False, error=f"Invalid JSON arguments for tool '{name}': {exc}"
            )
        if not isinstance(args, dict):
            return ToolResult(
                ok=False,
                error=f"Invalid JSON arguments for tool '{name}': expected object dict",
            )
        target = self._tools.get(name)
        if target is None:
            available = ", ".join(sorted(self._tools))
            return ToolResult(
                ok=False, error=f"Unknown tool '{name}'. Available: {available}"
            )
        return await target.execute(args)

    async def execute(self, tool_call: dict) -> ToolResult:
        """兼容别名：执行单个 tool_call。"""
        return await self.execute_tool_call(tool_call)

    async def execute_batch(self, tool_calls: list[dict]) -> list[ToolResult]:
        """批量执行工具调用（全员只读并发；只要包含一个写入则整批保序串行，防止因果时序倒置）。"""
        if not tool_calls:
            return []

        # 检查这批工具中是否包含任何不安全的写工具（或未知工具）
        has_sequential = any(
            (t := self._tools.get(tc.get("function", {}).get("name", ""))) is None
            or not t.is_parallel_safe
            for tc in tool_calls
        )

        if has_sequential:
            # 只要包含一个写操作，整批严格按大模型输出的原始顺序串行执行，确保因果顺序绝对正确
            return [await self.execute_tool_call(tc) for tc in tool_calls]

        # 全部都是只读安全工具时，安全并发执行
        return list(
            await asyncio.gather(*(self.execute_tool_call(tc) for tc in tool_calls))
        )
