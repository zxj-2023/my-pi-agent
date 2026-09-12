from __future__ import annotations

import difflib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from my_agent_core.tools import Tool, ToolResult, tool
from pydantic import BaseModel, ConfigDict, Field

from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.tools.base import is_binary_file, resolve_path

if not hasattr(FileMutationQueue, "acquire"):

    @asynccontextmanager
    async def _fmq_acquire(self: FileMutationQueue, path: Path) -> AsyncIterator[None]:
        lock = await self.get_lock(path)
        async with lock:
            yield

    FileMutationQueue.acquire = _fmq_acquire  # type: ignore[attr-defined]


@asynccontextmanager
async def _acquire_lock(queue: Any, path: Path) -> AsyncIterator[None]:
    if hasattr(queue, "acquire"):
        async with queue.acquire(path):
            yield
    elif hasattr(queue, "get_lock"):
        lock = await queue.get_lock(path)
        async with lock:
            yield
    else:
        yield


class EditBlock(BaseModel):
    """单个代码编辑块：精确旧文本与替换新文本。"""

    model_config = ConfigDict(populate_by_name=True)

    old_text: str = Field(
        ..., alias="oldText", description="Exact original code block to replace"
    )
    new_text: str = Field(
        ..., alias="newText", description="New code block to insert"
    )


@dataclass
class EditResult(ToolResult):
    """Edit 工具执行结果：继承 ToolResult，兼容字符串直接比较与包含操作。"""

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


def make_edit_tool(
    workspace: Path, mutation_queue: FileMutationQueue | None = None
) -> Tool:
    """创建工作区绑定的 edit 工具。

    - workspace: 工作区根目录路径
    - mutation_queue: 单文件并发互斥锁队列，缺省时自动新建
    """
    workspace = workspace.resolve()
    queue = mutation_queue or FileMutationQueue()

    @tool(
        name="edit",
        description="Surgically edit file using multi-edit atomic blocks and unified diff generation.",
        is_parallel_safe=True,
    )
    async def edit(
        path: str,
        edits: list[dict] | list[EditBlock] | None = None,
        old_text: str | None = None,
        new_text: str | None = None,
    ) -> str:
        try:
            target = resolve_path(workspace, path)
            if not target.exists():
                return f"Error: File not found: {path}"
            if target.is_dir():
                return f"Error: Path is a directory: {path}"
            if is_binary_file(target):
                return f"Error: Cannot edit binary file: {path}"

            # 1. 规范化 edits 入参
            edit_blocks: list[EditBlock] = []
            if edits is not None:
                if len(edits) == 0:
                    return "Error: No edits provided."
                for item in edits:
                    if isinstance(item, EditBlock):
                        edit_blocks.append(item)
                    elif isinstance(item, dict):
                        old_val = (
                            item.get("oldText")
                            if "oldText" in item
                            else item.get("old_text")
                        )
                        new_val = (
                            item.get("newText")
                            if "newText" in item
                            else item.get("new_text")
                        )
                        if old_val is None or new_val is None:
                            return (
                                "Error: Each edit block must contain 'oldText' (or 'old_text') "
                                "and 'newText' (or 'new_text')."
                            )
                        edit_blocks.append(
                            EditBlock(old_text=str(old_val), new_text=str(new_val))
                        )
                    else:
                        return f"Error: Invalid edit block type: {type(item).__name__}"
            elif old_text is not None and new_text is not None:
                edit_blocks.append(EditBlock(old_text=old_text, new_text=new_text))
            else:
                return "Error: Either 'edits' or ('old_text' and 'new_text') must be provided."

            if not edit_blocks:
                return "Error: No edits provided."

            async with _acquire_lock(queue, target):
                raw_bytes = target.read_bytes()

                # 2. 探测 BOM
                has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
                clean_bytes = raw_bytes[3:] if has_bom else raw_bytes
                try:
                    content = clean_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    return f"Error: File is not valid UTF-8: {path}"

                # 3. 探测换行符并统一归一化为 LF
                is_crlf = "\r\n" in content
                normalized_content = content.replace("\r\n", "\n")

                # 4. 预检所有 edit block（唯一匹配与非重叠校验）
                matches: list[tuple[int, int, str, str, int]] = []
                for i, b in enumerate(edit_blocks):
                    old_norm = b.old_text.replace("\r\n", "\n")
                    new_norm = b.new_text.replace("\r\n", "\n")
                    if not old_norm:
                        return f"Error: 'oldText' cannot be empty (edit #{i+1})."

                    count = normalized_content.count(old_norm)
                    if count == 0:
                        lines_count = len(normalized_content.splitlines())
                        return (
                            f"Error: 'oldText' not found in {path} (edit #{i+1}). "
                            f"The file has {lines_count} lines. Please read the file first to check exact indentation."
                        )
                    if count > 1:
                        return (
                            f"Error: 'oldText' matched {count} times in {path} (edit #{i+1}). "
                            f"Please provide more surrounding context lines to ensure a unique match."
                        )

                    idx = normalized_content.find(old_norm)
                    matches.append((idx, idx + len(old_norm), old_norm, new_norm, i + 1))

                # 5. 校验区间非重叠
                matches.sort(key=lambda m: (m[0], m[1]))
                for j in range(len(matches) - 1):
                    if matches[j][1] > matches[j + 1][0]:
                        e1 = matches[j][4]
                        e2 = matches[j + 1][4]
                        return (
                            f"Error: Overlapping edit regions detected between "
                            f"edit #{min(e1, e2)} and edit #{max(e1, e2)}."
                        )

                # 6. 逆序替换（Reverse replacement）
                modified_content = normalized_content
                for start, end, _, new_norm, _ in sorted(
                    matches, key=lambda m: m[0], reverse=True
                ):
                    modified_content = (
                        modified_content[:start] + new_norm + modified_content[end:]
                    )

                # 7. 生成 Unified Diff
                orig_lines = normalized_content.splitlines(keepends=True)
                mod_lines = modified_content.splitlines(keepends=True)
                display_path = path.replace("\\", "/")
                diff = "".join(
                    difflib.unified_diff(
                        orig_lines,
                        mod_lines,
                        fromfile=f"a/{display_path}",
                        tofile=f"b/{display_path}",
                        lineterm="\n",
                    )
                )

                # 8. 还原换行符与 BOM
                final_text = (
                    modified_content.replace("\n", "\r\n")
                    if is_crlf
                    else modified_content
                )
                out_bytes = final_text.encode("utf-8")
                if has_bom:
                    out_bytes = b"\xef\xbb\xbf" + out_bytes

                target.write_bytes(out_bytes)

                return (
                    f"Successfully applied {len(edit_blocks)} edit(s) to {path}.\n"
                    f"Diff:\n```diff\n{diff}```"
                )
        except Exception as e:
            return f"Error: {e}"

    orig_execute = edit.execute

    async def execute(
        args: dict[str, Any] | None = None,
        signal: Any | None = None,
        on_update: Callable[[Any], None] | None = None,
        tool_call_id: str | None = None,
        **kwargs: Any,
    ) -> EditResult:
        call_args = dict(args) if isinstance(args, dict) else {}
        call_args.update(kwargs)
        if "oldText" in call_args and "old_text" not in call_args:
            call_args["old_text"] = call_args.pop("oldText")
        if "newText" in call_args and "new_text" not in call_args:
            call_args["new_text"] = call_args.pop("newText")
        res = await orig_execute(
            call_args,
            signal=signal,
            on_update=on_update,
            tool_call_id=tool_call_id,
        )
        return EditResult(
            ok=res.ok,
            data=res.data,
            error=res.error,
            meta=res.meta,
            terminate=res.terminate,
        )

    edit.execute = execute
    return edit
