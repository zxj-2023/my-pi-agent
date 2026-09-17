from __future__ import annotations

import re
from pathlib import Path

from my_coding_agent.tools.base import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    is_binary_file,
    resolve_path,
)


class FileReferenceParser:
    """对标 Pig-Mono 的提示词 @ 文件引用解析与快照注入器。"""

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).resolve()

    def parse_references(self, text: str) -> list[str]:
        """从输入文本中匹配提取 @path/to/file 或 @filename 文件引用。"""
        pattern = r"@([\w\-./]+\.\w+)"
        matches = re.findall(pattern, text)
        # 去重保序
        seen: set[str] = set()
        unique_refs: list[str] = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique_refs.append(m)
        return unique_refs

    def resolve_reference(self, ref: str) -> tuple[bool, Path | None, str]:
        """解析引用并读取文件内容。"""
        try:
            target = resolve_path(self.workspace, ref)
            if not target.exists():
                return False, None, f"File not found: {ref}"
            if target.is_dir():
                return False, target, f"Path is a directory: {ref}"
            if is_binary_file(target):
                return False, target, f"Cannot reference binary file: {ref}"

            text = target.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            if len(lines) > DEFAULT_MAX_LINES:
                lines = lines[:DEFAULT_MAX_LINES]
                text = "\n".join(lines) + f"\n[File truncated at {DEFAULT_MAX_LINES} lines]"

            encoded = text.encode("utf-8")
            if len(encoded) > DEFAULT_MAX_BYTES:
                text = encoded[:DEFAULT_MAX_BYTES].decode("utf-8", errors="ignore") + "\n[File truncated at 50KB]"

            return True, target, text
        except Exception as e:
            return False, None, f"Error resolving file reference: {e}"

    def expand_references(self, text: str) -> str:
        """解析所有引用并将有效文件快照追加到提示词尾部。"""
        refs = self.parse_references(text)
        if not refs:
            return text

        injected_blocks: list[str] = []
        for r in refs:
            ok, target, content = self.resolve_reference(r)
            if ok and target:
                try:
                    rel_path = str(target.relative_to(self.workspace)).replace("\\", "/")
                except ValueError:
                    rel_path = str(target).replace("\\", "/")
                injected_blocks.append(f'<referenced_file path="{rel_path}">\n{content}\n</referenced_file>')

        if not injected_blocks:
            return text

        return text + "\n\n<referenced_files>\n" + "\n\n".join(injected_blocks) + "\n</referenced_files>"

    # 别名支持
    expand = expand_references
