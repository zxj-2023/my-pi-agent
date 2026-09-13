"""词级差异行内反色高亮渲染器 (diffWords)。

对齐 Pi diff.ts 哲学：
- 对 Unified Diff 中成对出现的 `-` 删行与 `+` 增行，进行词级分词比对 (SequenceMatcher)；
- 变动的词汇使用 Rich bold reverse（反色）突出加亮显示；
- 文件头与分块头 (---, +++, @@) 分别使用 bold cyan / bold magenta 显示；
- 单独的增删行保持常规绿/红底色。
"""

from __future__ import annotations

import difflib
import re

from rich.text import Text

__all__ = ["render_diff_with_word_highlight"]


def _split_tokens(s: str) -> list[str]:
    """拆分单词、空白与标点符号。"""
    return re.findall(r"\w+|\s+|[^\w\s]+", s)


def render_diff_with_word_highlight(diff_text: str) -> Text:
    """对齐 Pi diff.ts 哲学的词级行内精细反色高亮渲染器。"""
    out = Text()
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # 文件头与分块头保持青色/洋红色
        if line.startswith("---") or line.startswith("+++"):
            out.append(line + "\n", style="bold cyan")
            i += 1
        elif line.startswith("@@"):
            out.append(line + "\n", style="bold magenta")
            i += 1
        # 探测成对修改行 (- 后紧跟 +)
        elif line.startswith("-") and (i + 1 < len(lines)) and lines[i + 1].startswith("+"):
            del_line = line[1:]
            add_line = lines[i + 1][1:]

            del_tokens = _split_tokens(del_line)
            add_tokens = _split_tokens(add_line)
            matcher = difflib.SequenceMatcher(None, del_tokens, add_tokens)

            # 渲染删行
            out.append("-", style="bold red")
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                chunk = "".join(del_tokens[i1:i2])
                if tag in ("replace", "delete"):
                    out.append(chunk, style="bold red reverse")
                else:
                    out.append(chunk, style="red")
            out.append("\n")

            # 渲染增行
            out.append("+", style="bold green")
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                chunk = "".join(add_tokens[j1:j2])
                if tag in ("replace", "insert"):
                    out.append(chunk, style="bold green reverse")
                else:
                    out.append(chunk, style="green")
            out.append("\n")
            i += 2
        elif line.startswith("-"):
            out.append(line + "\n", style="red")
            i += 1
        elif line.startswith("+"):
            out.append(line + "\n", style="green")
            i += 1
        else:
            out.append(line + "\n", style="dim")
            i += 1
    return out
