"""Harbor sandbox tool registry bridging CodingAgent tools to BaseEnvironment."""

from __future__ import annotations

import asyncio
from typing import Any

from my_agent_core.registry import ToolRegistry
from my_agent_core.tools.core import ToolResult, tool

MAX_OUTPUT_CHARS = 50_000


class HarborToolRegistry(ToolRegistry):
    """Bridges the agent's workspace tools to Harbor's container BaseEnvironment."""

    def __init__(self, environment: Any):
        super().__init__()
        self.env = environment
        self._register_harbor_tools()

    async def execute(self, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        """Convenience alias for execute_tool."""
        return await self.execute_tool(name=name, args=args or {})

    def _register_harbor_tools(self) -> None:
        env = self.env

        @tool(
            name="bash",
            description="Execute a bash command inside the container environment.",
            prompt_snippet="Execute bash commands in container sandbox",
        )
        async def bash(command: str, timeout: float = 120.0) -> ToolResult:
            try:
                res = await asyncio.wait_for(env.exec(command), timeout=timeout)
                stdout = getattr(res, "stdout", "") or ""
                stderr = getattr(res, "stderr", "") or ""
                return_code = getattr(res, "return_code", 0)

                combined = stdout
                if stderr:
                    combined = f"{stdout}\nstderr:\n{stderr}" if stdout else stderr

                if len(combined) > MAX_OUTPUT_CHARS:
                    combined = combined[:MAX_OUTPUT_CHARS] + "\n... [Output truncated at 50KB]"

                if return_code != 0:
                    return ToolResult(
                        ok=False,
                        data=combined,
                        error=f"Command exited with code {return_code}: {stderr or stdout}",
                    )
                return ToolResult(ok=True, data=combined)
            except asyncio.TimeoutError:
                return ToolResult(ok=False, error=f"Command timed out after {timeout}s: {command}")
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error executing bash command: {exc}")

        @tool(
            name="read",
            description="Read file contents from the container environment with line numbers.",
            prompt_snippet="Read file contents with line numbers",
        )
        async def read(path: str, offset: int = 1, limit: int = 2000) -> ToolResult:
            try:
                content = await env.read_file(path)
                lines = content.splitlines()
                total_lines = len(lines)

                start_idx = max(0, offset - 1)
                end_idx = min(total_lines, start_idx + limit)
                selected_lines = lines[start_idx:end_idx]

                numbered_lines = [f"{start_idx + idx + 1:4d} | {line}" for idx, line in enumerate(selected_lines)]
                formatted = "\n".join(numbered_lines)
                if not formatted and total_lines == 0:
                    formatted = "(empty file)"

                return ToolResult(ok=True, data=formatted)
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error reading file '{path}': {exc}")

        @tool(
            name="write",
            description="Write content to a file inside the container environment.",
            prompt_snippet="Write content to container file",
        )
        async def write(path: str, content: str) -> ToolResult:
            try:
                normalized = content.replace("\r\n", "\n")
                await env.write_file(path, normalized)
                return ToolResult(
                    ok=True,
                    data=f"Successfully wrote {len(normalized.encode('utf-8'))} bytes to {path}",
                )
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error writing file '{path}': {exc}")

        @tool(
            name="edit",
            description="Surgically edit file inside container with exact matching on host.",
            prompt_snippet="Exact string replacement edit in container file",
        )
        async def edit(
            path: str,
            edits: list[dict[str, Any]] | None = None,
            old_text: str | None = None,
            new_text: str | None = None,
        ) -> ToolResult:
            try:
                # 1. Normalize edit blocks
                raw_edits = edits or []
                if old_text is not None:
                    raw_edits = [{"oldText": old_text, "newText": new_text or ""}]

                if not raw_edits:
                    return ToolResult(ok=False, error="No edits specified")

                # 2. Fetch original content from container
                content = await env.read_file(path)
                content = content.replace("\r\n", "\n")

                # 3. Perform surgical checks on host
                for edit_block in raw_edits:
                    target_old = edit_block.get("oldText") or edit_block.get("old_text") or ""
                    target_new = edit_block.get("newText") or edit_block.get("new_text") or ""
                    target_old = target_old.replace("\r\n", "\n")
                    target_new = target_new.replace("\r\n", "\n")

                    count = content.count(target_old)
                    if count == 0:
                        return ToolResult(
                            ok=False,
                            error=f"Could not find exact match for oldText in {path}: {target_old[:100]!r}",
                        )
                    if count > 1:
                        return ToolResult(
                            ok=False,
                            error=f"Found {count} times match for oldText in {path}. Must be uniquely matching.",
                        )
                    content = content.replace(target_old, target_new, 1)

                # 4. Write updated content back to container
                await env.write_file(path, content)
                return ToolResult(ok=True, data=f"Successfully applied {len(raw_edits)} edit(s) to {path}")
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error editing file '{path}': {exc}")

        @tool(
            name="ls",
            description="List directory contents inside container.",
            prompt_snippet="List container directory contents",
        )
        async def ls(path: str = ".") -> ToolResult:
            try:
                res = await env.exec(f"ls -la {path}")
                stdout = getattr(res, "stdout", "") or ""
                return ToolResult(ok=True, data=stdout)
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error listing directory '{path}': {exc}")

        @tool(
            name="grep",
            description="Search text patterns inside container files.",
            prompt_snippet="Search text in container files",
        )
        async def grep(pattern: str, path: str = ".", case_sensitive: bool = True) -> ToolResult:
            try:
                flag = "-rn" if case_sensitive else "-rni"
                res = await env.exec(f"grep {flag} {pattern!r} {path}")
                stdout = getattr(res, "stdout", "") or ""
                return ToolResult(ok=True, data=stdout)
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error searching text '{pattern}': {exc}")

        @tool(
            name="find",
            description="Find files matching pattern inside container.",
            prompt_snippet="Find files by name in container",
        )
        async def find(pattern: str = "*", path: str = ".") -> ToolResult:
            try:
                res = await env.exec(f"find {path} -name {pattern!r}")
                stdout = getattr(res, "stdout", "") or ""
                return ToolResult(ok=True, data=stdout)
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error finding files '{pattern}': {exc}")

        self.register(bash)
        self.register(read)
        self.register(write)
        self.register(edit)
        self.register(ls)
        self.register(grep)
        self.register(find)
