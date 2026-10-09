"""Harbor sandbox tool registry bridging CodingAgent tools to BaseEnvironment."""

from __future__ import annotations

import asyncio
import base64
import posixpath
import re
import shlex
from typing import Any

from my_agent_core.registry import ToolRegistry
from my_agent_core.tools.core import ToolResult, tool


class HarborToolRegistry(ToolRegistry):
    """Bridges the agent's workspace tools to Harbor's container BaseEnvironment."""

    def __init__(self, environment: Any, initial_cwd: str = "/app"):
        super().__init__()
        self.env = environment
        self._cwd: str = initial_cwd
        self._register_harbor_tools()

    @property
    def cwd(self) -> str:
        """Current tracked working directory inside the container."""
        return self._cwd

    def _resolve_path(self, path: str) -> str:
        """Resolve a path against the current working directory."""
        if not path or path == ".":
            return self._cwd
        if posixpath.isabs(path):
            return posixpath.normpath(path)
        return posixpath.normpath(posixpath.join(self._cwd, path))

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
                wrapped_cmd = (
                    f"cd {shlex.quote(self._cwd)} 2>/dev/null || true; "
                    "export DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat CI=true "
                    "PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ "
                    "PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu "
                    "PIP_TRUSTED_HOST='mirrors.aliyun.com download.pytorch.org'; "
                    f"{command}\n"
                    "__MY_PI_RC__=$?\n"
                    'echo "__MY_PI_CWD__:$(pwd)"\n'
                    "exit $__MY_PI_RC__"
                )
                res = await asyncio.wait_for(env.exec(wrapped_cmd), timeout=timeout)
                stdout = getattr(res, "stdout", "") or ""
                stderr = getattr(res, "stderr", "") or ""
                return_code = getattr(res, "return_code", 0)

                # Extract updated CWD if present
                cwd_match = re.search(r"__MY_PI_CWD__:(.+?)(?:\r?\n|$)", stdout)
                if cwd_match:
                    detected_cwd = cwd_match.group(1).strip()
                    if detected_cwd:
                        self._cwd = detected_cwd
                    stdout = re.sub(r"__MY_PI_CWD__:.+?(?:\r?\n|$)", "", stdout)

                combined = stdout
                if stderr:
                    combined = f"{stdout}\nstderr:\n{stderr}" if stdout else stderr

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
            prompt_guidelines=["Use read to examine files instead of cat or sed."],
        )
        async def read(path: str, offset: int = 1, limit: int = 2000) -> ToolResult:
            target_path = self._resolve_path(path)
            try:
                res = await env.exec(f"cat {shlex.quote(target_path)}")
                return_code = getattr(res, "return_code", 0)
                if return_code != 0:
                    return ToolResult(ok=False, error=f"File not found: '{target_path}'")

                content = getattr(res, "stdout", "") or ""
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
                return ToolResult(ok=False, error=f"Error reading file '{target_path}': {exc}")

        @tool(
            name="write",
            description="Create or overwrite files inside the container environment.",
            prompt_snippet="Create or overwrite files",
            prompt_guidelines=["Use write only for new files or complete rewrites."],
        )
        async def write(path: str, content: str) -> ToolResult:
            target_path = self._resolve_path(path)
            try:
                normalized = content.replace("\r\n", "\n")
                b64_payload = base64.b64encode(normalized.encode("utf-8")).decode("ascii")
                cmd = (
                    f"mkdir -p $(dirname {shlex.quote(target_path)}) && "
                    f"echo {shlex.quote(b64_payload)} | base64 -d > {shlex.quote(target_path)}"
                )
                res = await env.exec(cmd)
                return_code = getattr(res, "return_code", 0)
                if return_code != 0:
                    stderr = getattr(res, "stderr", "")
                    return ToolResult(ok=False, error=f"Failed to write file '{target_path}': {stderr}")
                return ToolResult(
                    ok=True,
                    data=f"Successfully wrote {len(normalized.encode('utf-8'))} bytes to {target_path}",
                )
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error writing file '{target_path}': {exc}")

        @tool(
            name="edit",
            description="Make precise file edits with exact text replacement inside the container.",
            prompt_snippet="Make precise file edits with exact text replacement, including multiple disjoint edits in one call",
            prompt_guidelines=[
                "Use edit for precise changes (edits[].oldText must match exactly)",
                "When changing multiple separate locations in one file, use one edit call with multiple entries in edits[] instead of multiple edit calls",
                "Each edits[].oldText is matched against the original file, not after earlier edits are applied. Do not emit overlapping or nested edits. Merge nearby changes into one edit.",
                "Keep edits[].oldText as small as possible while still being unique in the file. Do not pad with large unchanged regions.",
            ],
        )
        async def edit(
            path: str,
            edits: list[dict[str, Any]] | None = None,
            old_text: str | None = None,
            new_text: str | None = None,
        ) -> ToolResult:
            target_path = self._resolve_path(path)
            try:
                # 1. Normalize edit blocks
                raw_edits = edits or []
                if old_text is not None:
                    raw_edits = [{"oldText": old_text, "newText": new_text or ""}]

                if not raw_edits:
                    return ToolResult(ok=False, error="No edits specified")

                # 2. Fetch original content from container via cat
                res = await env.exec(f"cat {shlex.quote(target_path)}")
                return_code = getattr(res, "return_code", 0)
                if return_code != 0:
                    return ToolResult(ok=False, error=f"File not found: '{target_path}'")

                content = (getattr(res, "stdout", "") or "").replace("\r\n", "\n")

                # 3. Perform surgical checks on host
                for edit_block in raw_edits:
                    target_old = (edit_block.get("oldText") or edit_block.get("old_text") or "").replace("\r\n", "\n")
                    target_new = (edit_block.get("newText") or edit_block.get("new_text") or "").replace("\r\n", "\n")

                    count = content.count(target_old)
                    if count == 0:
                        return ToolResult(
                            ok=False,
                            error=f"Could not find exact match for oldText in {target_path}: {target_old[:100]!r}",
                        )
                    if count > 1:
                        return ToolResult(
                            ok=False,
                            error=f"Found {count} times match for oldText in {target_path}. Must be uniquely matching.",
                        )
                    content = content.replace(target_old, target_new, 1)

                # 4. Write updated content back to container via base64 pipe
                b64_payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
                cmd = f"echo {shlex.quote(b64_payload)} | base64 -d > {shlex.quote(target_path)}"
                w_res = await env.exec(cmd)
                w_rc = getattr(w_res, "return_code", 0)
                if w_rc != 0:
                    stderr = getattr(w_res, "stderr", "")
                    return ToolResult(ok=False, error=f"Failed to save edit to '{target_path}': {stderr}")

                return ToolResult(ok=True, data=f"Successfully applied {len(raw_edits)} edit(s) to {target_path}")
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error editing file '{target_path}': {exc}")

        @tool(
            name="ls",
            description="List directory contents inside container.",
            prompt_snippet="List container directory contents",
        )
        async def ls(path: str = ".") -> ToolResult:
            target_path = self._resolve_path(path)
            try:
                res = await env.exec(f"ls -la {shlex.quote(target_path)}")
                stdout = getattr(res, "stdout", "") or ""
                return ToolResult(ok=True, data=stdout)
            except Exception as exc:
                return ToolResult(ok=False, error=f"Error listing directory '{target_path}': {exc}")

        @tool(
            name="grep",
            description="Search text patterns inside container files.",
            prompt_snippet="Search text in container files",
        )
        async def grep(pattern: str, path: str = ".", case_sensitive: bool = True) -> ToolResult:
            target_path = self._resolve_path(path)
            try:
                flag = "-rn" if case_sensitive else "-rni"
                res = await env.exec(f"grep {flag} {shlex.quote(pattern)} {shlex.quote(target_path)}")
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
            target_path = self._resolve_path(path)
            try:
                res = await env.exec(f"find {shlex.quote(target_path)} -name {shlex.quote(pattern)}")
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
