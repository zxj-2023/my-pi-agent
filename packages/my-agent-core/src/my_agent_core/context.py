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


SUMMARIZATION_SYSTEM_PROMPT = (
    "You are a context summarization assistant. "
    "Do NOT continue the conversation. Do NOT respond to any questions. "
    "ONLY output the summary."
)

SUMMARIZATION_PROMPT_TEMPLATE = (
    "Summarize this conversation so work can continue. "
    "Preserve: 1. current goal, 2. key findings/decisions, "
    "3. remaining work, 4. user constraints.\n"
    "Format:\n## Goal\n## Progress (Done / In Progress / Blocked)\n"
    "## Key Decisions\n## Next Steps\n\n"
    "Previous summary:\n{previous_summary}\n\n"
    "Conversation:\n{conversation}"
)

SUMMARY_MESSAGE_PREFIX = "[Context summary — earlier conversation compacted]\n\n"


class CompactionInfo:
    """一次压缩的信息（Agent 消费：事件 + 写回 session）。"""

    def __init__(self, *, tokens_before: int, tokens_after: int, summarized_count: int,
                 summary: str, covered_count: int, retained_tail: list[dict],
                 summary_usage: dict | None, summary_model: str | None):
        self.tokens_before = tokens_before
        self.tokens_after = tokens_after
        self.summarized_count = summarized_count
        self.summary = summary
        self.covered_count = covered_count
        self.retained_tail = retained_tail
        self.summary_usage = summary_usage
        self.summary_model = summary_model


def _serialize_messages(messages: list[Message]) -> str:
    """逐条 'role: content'（tool_calls 只列名称）——摘要器好读，省 token。"""
    lines = []
    for m in messages:
        if m.role == "assistant" and m.metadata and m.metadata.get("tool_calls"):
            names = [tc.get("function", {}).get("name", "?") for tc in m.metadata["tool_calls"]]
            lines.append(f"assistant: [tool_calls: {', '.join(names)}] {m.content}")
        elif m.role == "tool":
            lines.append(f"tool: {m.content[:4000]}")
        else:
            lines.append(f"{m.role}: {m.content}")
    return "\n".join(lines)


class ContextManager:
    """四层压缩管线 + usage 锚定估算 + retainedTail 缓存。

    纯视图逻辑：prepare 只返回新 list，绝不修改传入 messages；缓存/树交互由 Agent 做。
    """

    def __init__(self, *, budget: int, llm, keep_recent_tokens: int | None = None,
                 results_dir: Path | None = None):
        self.budget = budget
        self.llm = llm
        self.keep_recent_tokens = keep_recent_tokens if keep_recent_tokens is not None else budget // 4
        self.results_dir = Path(results_dir) if results_dir else None
        self._summary: str | None = None
        self._covered_count: int | None = None
        self._retained_tail: list[dict] | None = None
        self._ratio: float | None = None
        self._last_view_chars = 0
        self.pending_compaction: CompactionInfo | None = None

    def restore_cache(self, *, summary: str, covered_count: int,
                      retained_tail: list[dict]) -> None:
        """从 session 缓存 entry 恢复（Agent 构造时调用）。"""
        self._summary = summary
        self._covered_count = covered_count
        self._retained_tail = retained_tail

    def record_usage(self, usage: dict | None) -> None:
        """每轮 llm.chat 后喂 usage → 更新锚定比例（ratio = 实测 prompt_tokens / 上次视图字符数）。"""
        if usage and usage.get("prompt_tokens") and self._last_view_chars:
            self._ratio = int(usage["prompt_tokens"]) / self._last_view_chars

    def prepare(self, messages: list[Message]) -> list[Message]:
        """四层管线 → 返回发送视图（非破坏）。有缓存先试缓存视图；仍超阈 → 迭代再摘要。"""
        self.pending_compaction = None
        if self._summary is not None:
            view = self._prepare_with_cache(messages)
            self._last_view_chars = _chars_of(view)
            if estimate_tokens(view) <= int(self.budget * 0.8):
                return view
            # 缓存视图仍超阈 → 迭代再摘要（_call_summarizer 附旧摘要）
            return self._do_summarize(messages)
        view = list(messages)
        view = budget_tool_results(view, results_dir=self.results_dir)
        view = snip_messages(view)
        view = micro_compact(view)
        self._last_view_chars = _chars_of(view)
        if estimate_tokens(view) <= int(self.budget * 0.8):
            return view
        return self._do_summarize(messages)

    def reset(self) -> None:
        """清缓存 + 锚定（Agent.reset 时调用）。"""
        self._summary = None
        self._covered_count = None
        self._retained_tail = None
        self._ratio = None
        self.pending_compaction = None

    def force_compact(self, messages: list[Message]) -> list[Message]:
        """无条件执行一次摘要（手动 compact 用），不管阈值。清缓存后基于完整历史重摘要。

        对话过短（正常切点逻辑找不到 cut）时仍强制：摘要全部非 system 消息，不保留尾部。
        """
        self._summary = None
        self._covered_count = None
        self._retained_tail = None
        cut = self._find_cut(messages)
        if cut is None:
            start = 1 if (messages and messages[0].role == "system") else 0
            if len(messages) <= start:
                return list(messages)  # 空 / 仅 system → 无可摘要
            cut = len(messages)  # 强制：全部非 system 消息进摘要，不保留尾部
        return self._summarize_from_cut(messages, cut)

    # ── 内部 ──

    def _prepare_with_cache(self, messages: list[Message]) -> list[Message]:
        """缓存分支：原 system + 摘要 + retained_tail 快照 + 之后新增。"""
        assert self._summary is not None and self._covered_count is not None
        assert self._retained_tail is not None
        system_msg = [messages[0]] if messages and messages[0].role == "system" else []
        tail_len = len(self._retained_tail)
        start = self._covered_count + tail_len
        newly = messages[start:] if len(messages) > start else []
        view = system_msg + [Message(role="user", content=SUMMARY_MESSAGE_PREFIX + self._summary)]
        view += [Message(**d) for d in self._retained_tail]
        view += newly
        return view

    def _do_summarize(self, messages: list[Message]) -> list[Message]:
        """无缓存时的首次压缩（或缓存失效的后备）。定 cut → 摘要调用 → 写缓存。"""
        cut = self._find_cut(messages)
        if cut is None:
            return list(messages)  # 找不到 user 切点 → 不压缩
        return self._summarize_from_cut(messages, cut)

    def _summarize_from_cut(self, messages: list[Message], cut: int) -> list[Message]:
        """按既定 cut 执行摘要：调 LLM → 写缓存 → 构造视图。降级失败返回原视图。"""
        tokens_before = estimate_tokens(messages, self._ratio)
        system_msg = [messages[0]] if messages and messages[0].role == "system" else []
        summarized = messages[len(system_msg):cut]  # 摘要输入不含 system（persona 保持原样）
        retained = messages[cut:]
        try:
            summary, usage, model = self._call_summarizer(summarized)
        except Exception:
            return list(messages)  # 降级：不压缩
        if not summary.strip():
            return list(messages)  # 空摘要视同失败
        self._summary = summary
        self._covered_count = cut
        self._retained_tail = [m.model_dump() for m in retained]
        self.pending_compaction = CompactionInfo(
            tokens_before=tokens_before,
            tokens_after=estimate_tokens(retained, self._ratio),
            summarized_count=cut,
            summary=summary,
            covered_count=cut,
            retained_tail=list(self._retained_tail),
            summary_usage=usage,
            summary_model=model,
        )
        view = system_msg + [Message(role="user", content=SUMMARY_MESSAGE_PREFIX + summary)] + retained
        self._last_view_chars = _chars_of(view)
        return view

    def _find_cut(self, messages: list[Message]) -> int | None:
        """从尾向前累积字符达 keep_recent_tokens → cut；向前对齐到 user 边界。"""
        budget_chars = self.keep_recent_tokens * 4
        acc = 0
        cut = len(messages)
        for i in range(len(messages) - 1, 0, -1):  # 跳过 system（index 0）
            acc += len(messages[i].content)
            if acc >= budget_chars:
                cut = i
                break
        if cut == len(messages):
            return None  # 尾部未达预算 → 全部当尾？不压缩
        # 对齐到 user 边界（不拆 assistant(tool_calls)+tool）
        while cut > 1 and messages[cut - 1].role != "user":
            cut -= 1
        if cut <= 1:
            return None
        return cut

    def _call_summarizer(self, messages: list[Message]) -> tuple[str, dict | None, str | None]:
        """调 self.llm 做摘要调用（tools=[]）→ (摘要, usage, model)。迭代：附旧摘要。"""
        conversation = _serialize_messages(messages)
        user_content = SUMMARIZATION_PROMPT_TEMPLATE.format(
            previous_summary=self._summary or "(none)",
            conversation=conversation,
        )
        resp = self.llm.chat(
            messages=[Message(role="system", content=SUMMARIZATION_SYSTEM_PROMPT),
                      Message(role="user", content=user_content)],
            tools=[],
        )
        return resp.content, resp.usage, resp.model


def _chars_of(messages: list[Message]) -> int:
    return len(json.dumps([m.model_dump() for m in messages], ensure_ascii=False, default=str))