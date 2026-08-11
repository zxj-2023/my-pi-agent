"""Context 管理测试：估算 + 三层免费压缩（context 设计文档 §8 #1、#4–#6）。"""
import json
from pathlib import Path

from my_agent_core.context import (
    budget_tool_results, estimate_tokens, micro_compact, snip_messages,
)
from my_agent_llm import Message, Response


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


class FakeLLM:
    """替身：按脚本返回 Response，记录收到的请求（tools=[] 区分摘要请求）。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages), "tools": tools})
        return self.responses.pop(0)


def _response(content: str = "", usage: dict | None = None) -> Response:
    return Response(content=content, model="fake", usage=usage)


def _small_ctx(llm, budget=10000, **kw):
    from my_agent_core.context import ContextManager

    return ContextManager(budget=budget, llm=llm, **kw)


def test_prepare_below_threshold_no_summary():
    """阈值下不触发：估算 < 0.8·budget → 无摘要请求（#3）。"""
    llm = FakeLLM([_response(content="ok")])
    ctx = _small_ctx(llm, budget=100_000)
    msgs = [_msg("user", "hi")]
    view = ctx.prepare(msgs)
    assert view == msgs
    assert len(llm.calls) == 0  # 无摘要调用


def test_prepare_trigger_summary_non_destructive():
    """超阈触发：视图 = [摘要 + 尾部]；原 messages 未修改（#7）。"""
    llm = FakeLLM([_response(content="## Goal\n...")])
    ctx = _small_ctx(llm, budget=1000, keep_recent_tokens=100)
    msgs = [_msg("user", "x" * 300) for _ in range(20)]  # 大幅超阈
    view = ctx.prepare(msgs)
    assert len(llm.calls) == 1
    assert llm.calls[0]["tools"] == []                    # 摘要调用 tools 为空
    assert view[0].role == "system" and "[Context summary" in view[0].content
    assert len(msgs) == 20                                # 原 messages 未修改


def test_summary_call_shape():
    """摘要调用形态：tools=[]、system 含"不要续聊"约束、user 含结构化格式（#8）。"""
    from my_agent_core.context import SUMMARIZATION_SYSTEM_PROMPT

    llm = FakeLLM([_response(content="## Goal\n...")])
    ctx = _small_ctx(llm, budget=1000, keep_recent_tokens=100)
    msgs = [_msg("user", "x" * 300) for _ in range(20)]
    ctx.prepare(msgs)
    assert llm.calls[0]["messages"][0].role == "system"
    assert "Do NOT continue the conversation" in llm.calls[0]["messages"][0].content
    assert "## Goal" in llm.calls[0]["messages"][1].content


def test_cache_reused_no_resummary():
    """缓存复用：prepare 后再 prepare 无新增 → 摘要调用仅 1 次（#9）。"""
    llm = FakeLLM([_response(content="## Goal\n...")])
    ctx = _small_ctx(llm, budget=1000, keep_recent_tokens=100)
    msgs = [_msg("user", "x" * 300) for _ in range(20)]
    view1 = ctx.prepare(msgs)
    view2 = ctx.prepare(msgs)  # 无新增
    assert len(llm.calls) == 1
    assert view1 == view2


def test_iterative_resummary():
    """迭代再摘要：压缩后继续增长再超阈 → 第二次摘要含第一次摘要内容（#10）。"""
    llm = FakeLLM([_response(content="first summary"), _response(content="second summary")])
    ctx = _small_ctx(llm, budget=1000, keep_recent_tokens=100)
    msgs = [_msg("user", "x" * 300) for _ in range(20)]
    ctx.prepare(msgs)
    # 大幅增长 → 触发第二次摘要
    more = msgs + [_msg("user", "y" * 300) for _ in range(20)]
    ctx.prepare(more)
    assert len(llm.calls) == 2
    summary_input = llm.calls[1]["messages"]
    assert any("first summary" in str(m.content) for m in summary_input)  # 旧摘要进输入


def test_summary_failure_degrades():
    """摘要失败降级：摘要调用抛异常 → 返回原视图（#13）。"""

    class BoomLLM:
        def chat(self, *, messages, tools=None, **kwargs):
            raise RuntimeError("api down")

    ctx = _small_ctx(BoomLLM(), budget=1000, keep_recent_tokens=100)
    msgs = [_msg("user", "x" * 300) for _ in range(20)]
    view = ctx.prepare(msgs)
    assert view == msgs  # 降级返回原视图


def test_usage_ratio_anchoring():
    """usage 锚定：record_usage 后 ratio 建立（#15 的 context 侧）。"""
    llm = FakeLLM([_response(content="## Goal", usage={"prompt_tokens": 1000})])
    ctx = _small_ctx(llm, budget=100_000)
    msgs = [_msg("user", "x" * 100) for _ in range(10)]
    ctx.prepare(msgs)                 # 未超阈 → 记录 _last_view_chars
    ctx.record_usage({"prompt_tokens": 1000})
    assert ctx._ratio is not None and 0 < ctx._ratio < 2  # ratio = 1000/序列化字符数