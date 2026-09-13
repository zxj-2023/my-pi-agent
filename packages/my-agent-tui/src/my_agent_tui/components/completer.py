from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from my_coding_agent.tools.base import DEFAULT_IGNORE_DIRS
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document


class FileReferenceCompleter(Completer):
    """对标 Pig-TUI advanced.py 的 @ 文件引用路径智能补全器。"""

    def __init__(self, workspace: Path | str, base_completer: Completer | None = None) -> None:
        self.workspace = Path(workspace).resolve()
        self.base_completer = base_completer

    def get_completions(self, document: Document, complete_event: CompleteEvent | None = None) -> Iterator[Completion]:
        text_before_cursor = document.get_word_before_cursor(WORD=True)

        if text_before_cursor.startswith("@"):
            query = text_before_cursor[1:].replace("\\", "/").lower()

            for root, dirs, files in os.walk(self.workspace):
                dirs[:] = sorted(d for d in dirs if d not in DEFAULT_IGNORE_DIRS)
                for f in sorted(files):
                    full_p = Path(root) / f
                    try:
                        rel = str(full_p.relative_to(self.workspace)).replace("\\", "/")
                    except ValueError:
                        continue

                    if query in rel.lower() or query in f.lower():
                        yield Completion(
                            text=f"@{rel}",
                            start_position=-len(text_before_cursor),
                            display=f"@{rel}",
                            display_meta="file",
                        )
            return

        if self.base_completer:
            yield from self.base_completer.get_completions(document, complete_event)  # type: ignore[arg-type]
