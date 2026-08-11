"""Context 管理：四层压缩管线（cheap-first）+ usage 锚定估算。

设计文档：docs/superpowers/specs/2026-08-01-my-agent-context-design.md（2026-08-11 修订版）。
本模块只做"视图变换"（非破坏，绝不修改传入 list）；树/文件由 Session 管。
"""
from __future__ import annotations

import json
from pathlib import Path

from my_agent_llm import Message

CHARS_PER_TOKEN = 4


def estimate_tokens(messages: list[Message], ratio: float | None = None) -> int:
    """估算 token 数。ratio 为 usage 锚定比例（每字符 token 数）；None 用 chars/4 兜底。"""
    chars = len(json.dumps([m.model_dump() for m in messages], ensure_ascii=False, default=str))
    if ratio is not None:
        return max(1, round(chars * ratio))
    return max(1, chars // CHARS_PER_TOKEN)


def _has_tool_calls(msg: Message) -> bool:
    return bool(msg.metadata and msg.metadata.get("tool_calls"))


def snip_messages(messages: list[Message], max_messages: int = 50) -> list[Message]:
    """L1：len > max_messages → 留头 3 + 尾 (max-4)，中间删，插一条 [snipped N] 占位。

    占位符计入预算，故尾留 max-4（3 头 + 1 占位 + max-4 尾 = max_messages）。
    边界：不拆开 assistant(tool_calls)+tool 配对（协议配对不变式）。
    """
    if len(messages) <= max_messages:
        return messages
    keep_head, keep_tail = 3, max_messages - 4
    head_end = keep_head
    tail_start = len(messages) - keep_tail
    # 头边界：head_end-1 是 assistant(tool_calls) → 并进后续 tool 消息
    if head_end > 0 and _has_tool_calls(messages[head_end - 1]):
        while head_end < len(messages) and messages[head_end].role == "tool":
            head_end += 1
    # 尾边界：tail_start 是 tool 且前一条是 assistant(tool_calls) → 并进
    if (tail_start > 0 and tail_start < len(messages)
            and messages[tail_start].role == "tool"
            and _has_tool_calls(messages[tail_start - 1])):
        tail_start -= 1
    if head_end >= tail_start:
        return messages
    snipped = tail_start - head_end
    placeholder = Message(role="user", content=f"[snipped {snipped} messages from conversation middle]")
    return messages[:head_end] + [placeholder] + messages[tail_start:]


def micro_compact(messages: list[Message], keep_recent: int = 5,
                  min_chars: int = 200) -> list[Message]:
    """L2：非最近 keep_recent 条、content > min_chars 的 tool 消息 → content 换占位符。

    metadata（tool_call_id 等）不动——配对不变式保住。
    """
    result = list(messages)
    tool_indices = [i for i, m in enumerate(result) if m.role == "tool"]
    for i in tool_indices[:-keep_recent]:
        if len(result[i].content) > min_chars:
            result[i] = result[i].model_copy(update={"content": "[Earlier tool result compacted]"})
    return result


def budget_tool_results(messages: list[Message], max_chars: int = 20000,
                        results_dir: Path | None = None) -> list[Message]:
    """L3：content 超 max_chars 的 tool 消息 → 落盘到 results_dir/<tool_call_id>.txt，视图换预览。

    落盘失败（results_dir 为 None / IO 错误）→ 保留原 content（降级）。
    """
    result = list(messages)
    for i, m in enumerate(result):
        if m.role != "tool" or len(m.content) <= max_chars:
            continue
        if results_dir is None:
            continue
        try:
            results_dir.mkdir(parents=True, exist_ok=True)
            tid = str(m.metadata.get("tool_call_id", i)) if m.metadata else str(i)
            path = results_dir / f"{tid}.txt"
            path.write_text(m.content, encoding="utf-8")
        except OSError:
            continue  # 降级：保留原 content
        result[i] = result[i].model_copy(update={
            "content": f"<persisted-output>\nFull: {path}\nPreview:\n{m.content[:2000]}\n</persisted-output>",
        })
    return result