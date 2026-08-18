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

    async def execute(self, tool_call: dict) -> ToolResult:
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

    async def execute_batch(self, tool_calls: list[dict]) -> list[ToolResult]:
        """批量执行工具调用（读写分离并发 + 预分配插槽严格保序回填）。"""
        if not tool_calls:
            return []

        results: list[ToolResult | None] = [None] * len(tool_calls)
        parallel_indices: list[int] = []
        sequential_indices: list[int] = []

        for i, tc in enumerate(tool_calls):
            name = tc.get("function", {}).get("name", "")
            target = self._tools.get(name)
            if target and target.is_parallel_safe:
                parallel_indices.append(i)
            else:
                sequential_indices.append(i)

        # 1. 并发只读安全工具
        if parallel_indices:
            parallel_tasks = [self.execute(tool_calls[i]) for i in parallel_indices]
            parallel_results = await asyncio.gather(*parallel_tasks)
            for idx, res in zip(parallel_indices, parallel_results, strict=False):
                results[idx] = res

        # 2. 串行写入有副作用工具
        for idx in sequential_indices:
            results[idx] = await self.execute(tool_calls[idx])

        return [r for r in results if r is not None]
