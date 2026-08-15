"""工具注册表 —— 持有工具集合，按名字查表与执行。"""
from __future__ import annotations

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

    def execute(self, tool_call: dict) -> ToolResult:
        """执行单个 tool_call（收协议 dict）。任何错误都转成 ToolResult，永不抛。"""
        name = tool_call["function"]["name"]
        try:
            args = json.loads(tool_call["function"]["arguments"])
        except (json.JSONDecodeError, TypeError) as exc:
            return ToolResult(ok=False, error=f"Invalid JSON arguments for tool '{name}': {exc}")
        target = self._tools.get(name)
        if target is None:
            available = ", ".join(sorted(self._tools))
            return ToolResult(ok=False, error=f"Unknown tool '{name}'. Available: {available}")
        return target.execute(args)
