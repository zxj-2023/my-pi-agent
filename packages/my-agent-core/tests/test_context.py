"""Context 管理测试：估算 + 三层免费压缩（context 设计文档 §8 #1、#4–#6）。"""
import json
from pathlib import Path

from my_agent_core.context import (
    budget_tool_results, estimate_tokens, micro_compact, snip_messages,
)
from my_agent_llm import Message


def _msg(role: str, content: str, **metadata) -> Message:
    return Message(role=role, content=content, metadata=metadata or None)


def test_estimate_tokens_monotonic():
    """估算随消息增长单调递增；空列表≈0；ratio 修正（#1）。"""
    assert estimate_tokens([]) <= estimate_tokens([_msg("user", "hi")])
    big = [_msg("user", "x" * 1000)] * 10
    small = [_msg("user", "x" * 10)] * 10
    assert estimate_tokens(big) > estimate_tokens(small)
    # ratio 锚定：ratio=1.0（每字符 1 token）→ 估算 ≈ 字符数
    assert estimate_tokens(big, ratio=1.0) > estimate_tokens(big, ratio=0.1)


def test_snip_keeps_pairing():
    """L1：>50 消息裁中间 + [snipped] 占位，不拆 assistant(tool_calls)+tool 配对（#5）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
    msgs = [_msg("user", f"q{i}") for i in range(40)]
    msgs.append(_msg("assistant", "", tool_calls=tc))   # index 40
    msgs.append(_msg("tool", "result"))                  # index 41（配对）
    msgs += [_msg("user", f"t{i}") for i in range(15)]   # 共 57 条
    view = snip_messages(msgs)
    assert len(view) <= 50
    assert any(m.content.startswith("[snipped") for m in view)
    # 配对完整：view 里 assistant(tool_calls) 后紧跟 tool
    for i, m in enumerate(view):
        if m.role == "assistant" and m.metadata and m.metadata.get("tool_calls"):
            assert i + 1 < len(view) and view[i + 1].role == "tool"


def test_snip_below_limit_noop():
    """L1：≤50 消息原样返回（#5）。"""
    msgs = [_msg("user", f"q{i}") for i in range(10)]
    assert snip_messages(msgs) == msgs


def test_micro_compact_old_tool_results():
    """L2：旧 tool 消息（>200 字符、非最近 5 条）→ 占位，metadata 保留（#6）。"""
    msgs = [_msg("tool", "y" * 500, tool_call_id=f"c{i}") for i in range(8)]
    view = micro_compact(msgs)
    assert view[0].content == "[Earlier tool result compacted]"
    assert view[0].metadata["tool_call_id"] == "c0"       # metadata 保留
    assert view[-1].content == "y" * 500                   # 最近 5 条不动
    orig = [_msg("tool", "y" * 500, tool_call_id="c9")]
    assert micro_compact(orig) == orig                     # 不足 keep_recent 不动


def test_budget_persists_large_tool_result(tmp_path):
    """L3：超大 tool 消息 → 落盘 + 视图换预览；原 messages 未修改（#4）。"""
    big = _msg("tool", "z" * 100, tool_call_id="c1")
    msgs = [_msg("user", "q"), big]
    view = budget_tool_results(msgs, max_chars=50, results_dir=tmp_path)
    assert "<persisted-output>" in view[1].content
    assert "Preview" in view[1].content
    assert len(msgs[1].content) == 100                       # 原 messages 未改
    assert (tmp_path / "c1.txt").exists()
    # 小结果不落盘
    small = [_msg("tool", "tiny", tool_call_id="c2")]
    assert budget_tool_results(small, max_chars=50, results_dir=tmp_path) == small