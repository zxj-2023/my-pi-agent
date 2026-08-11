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
    """替身：按脚本返回 Response，耗尽后返回 default；记录请求（tools=[] 区分摘要）。"""

    def __init__(self, responses: list[Response] | None = None,
                 default: Response | None = None):
        self.responses = list(responses or [])
        self.default = default or Response(content="ok", model="fake")
        self.calls: list[dict] = []

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages), "tools": tools})
        if self.responses:
            return self.responses.pop(0)
        return self.default


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
    assert view[0].role == "user" and "[Context summary" in view[0].content
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


# ── Agent 集成（Task 4）──

from my_agent_core.agent import Agent
from my_agent_core.session import Session
from my_agent_core.tools import tool


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


def _agent(llm, *, tools=(multiply,), **kw) -> Agent:
    return Agent(llm=llm, tools=list(tools), **kw)


def test_context_budget_none_unchanged():
    """未启用：context_budget=None → llm 收到的 messages 与 transcript 全等（#2）。"""
    llm = FakeLLM([_response(content="hi")])
    agent = _agent(llm)
    agent.run("hello")
    # llm 调用发生在 assistant 回复追加之前 → 收到的即调用时刻的完整 transcript
    assert llm.calls[0]["messages"] == agent.messages[:-1]


def test_agent_trigger_compaction_and_event(tmp_path):
    """完整 run 触发压缩 → ContextCompacted 恰发射；session 写缓存 entry + floor + system 保留（#11、#14）。"""
    from my_agent_core.events import ContextCompacted

    llm = FakeLLM(default=_response(content="## Goal\n..."))
    session = Session(path=tmp_path / "s.jsonl", system_prompt="sys")
    agent = _agent(llm, session=session, context_budget=400, keep_recent_tokens=100)
    events: list[ContextCompacted] = []
    agent.register_hook(ContextCompacted, lambda ev: (events.append(ev), None)[1])
    for _ in range(6):  # 累积 6 条大消息 → 超阈触发摘要
        agent.run("y" * 300)
    assert len(events) >= 1
    assert events[0].tokens_before > events[0].tokens_after
    # session 缓存 entry + floor
    cache_entries = [e for e in session.tree.entries.values() if e.type == "compaction"]
    assert cache_entries
    assert "retained_tail" in cache_entries[0].metadata
    assert session.compaction_floor is not None


def test_cache_persist_across_agents(tmp_path):
    """压缩后新 Agent 同 session → 构造恢复免摘要；prepare 视图 system 保留 + 摘要 user（#11 + pointer）。"""
    llm1 = FakeLLM(default=_response(content="## Goal\n..."))
    session = Session(path=tmp_path / "s.jsonl", system_prompt="sys")
    agent1 = _agent(llm1, session=session, context_budget=400, keep_recent_tokens=100)
    for _ in range(6):
        agent1.run("y" * 300)
    # “进程 2”：新 Agent 同 session
    llm2 = FakeLLM()
    agent2 = _agent(llm2, session=session, context_budget=400, keep_recent_tokens=100)
    # 构造时恢复缓存（免摘要）
    assert agent2._ctx._summary is not None
    assert len(llm2.calls) == 0
    # prepare 视图：原 system 保留在首 + 摘要 user 消息
    agent2.messages.append(Message(role="user", content="继续"))
    view = agent2._ctx.prepare(agent2.messages)
    assert view[0].role == "system" and view[0].content == "sys"  # 原 persona
    assert view[1].role == "user" and "[Context summary" in view[1].content  # 摘要 user
    assert len(llm2.calls) == 0  # 免重算


def test_rewind_guard_blocks_after_compaction(tmp_path):
    """压缩后 rewind 到压缩点前 → ValueError（#12 agent 侧）。"""
    llm = FakeLLM(default=_response(content="## Goal\n..."))
    session = Session(path=tmp_path / "s.jsonl", system_prompt="sys")
    agent = _agent(llm, session=session, context_budget=400, keep_recent_tokens=100)
    for _ in range(6):
        agent.run("y" * 300)
    first_user = next(e for e in session.tree.entries.values()
                      if e.role == "user" and e.content == "y" * 300)
    try:
        session.rewind(first_user.id)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError (rewind before floor)")


def test_manual_compact():
    """手动 compact()：无条件触发一次摘要 + 写缓存 + 事件；不动 messages（#16）。"""
    from my_agent_core.events import ContextCompacted

    llm = FakeLLM(default=_response(content="## Manual summary"))
    agent = _agent(llm, context_budget=100_000)  # 阈值很高，正常不会自动触发
    events: list[ContextCompacted] = []
    agent.register_hook(ContextCompacted, lambda ev: (events.append(ev), None)[1])
    agent.run("hi")  # 1 条消息，不触发
    assert len(llm.calls) == 1  # 只有对话请求
    agent.compact()             # 手动强制（无条件摘要）
    assert len(llm.calls) >= 2  # 摘要请求
    assert len(events) == 1
    assert agent._ctx._summary is not None
    # run("hi") 后 transcript = [user(hi), assistant(回复)]，compact 不动 messages → 仍 2 条
    assert len(agent.messages) == 2


def test_usage_ratio_feeds_trigger_threshold():
    """usage 锚定接入触发：ratio 建立后，阈值估算用比例（final review F1）。"""
    msgs = [_msg("user", "x" * 300) for _ in range(6)]  # 序列化 ~2106 字符
    # 无锚场景：ratio=None → chars/4（2106/4=526 < 800 阈值，不触发）
    llm_none = FakeLLM([_response(content="ok")])
    ctx_none = _small_ctx(llm_none, budget=1000, keep_recent_tokens=100)
    ctx_none.prepare(msgs)
    assert len(llm_none.calls) == 0  # chars/4 估算不触发
    # 有锚场景：ratio=0.5 → 2106*0.5≈1053 > 800 → 触发（锚让估算上升）
    llm_anchor = FakeLLM([_response(content="## Goal\n...")])
    ctx_anchor = _small_ctx(llm_anchor, budget=1000, keep_recent_tokens=100)
    ctx_anchor._ratio = 0.5  # 直接设锚（模拟 record_usage 已建立）
    ctx_anchor.prepare(msgs)
    assert len(llm_anchor.calls) == 1  # 锚使估算超阈 → 触发


def test_bridge_restore_and_write(tmp_path):
    """ContextSessionBridge 独立测试：write 写回 session、restore 从 session 恢复（桥类重构）。"""
    from my_agent_core.context import ContextManager, ContextSessionBridge

    # store 式路径：<ws>/.my_agent_core/sessions/<id>.jsonl
    session = Session(path=tmp_path / ".my_agent_core" / "sessions" / "s.jsonl", system_prompt="sys")
    bridge = ContextSessionBridge(session)
    # L3 落盘目录：parent.parent = <ws>/.my_agent_core
    assert bridge.results_dir() == tmp_path / ".my_agent_core" / "tool-results"
    # write：压缩 → 写回 session
    llm = FakeLLM([_response(content="## G")])
    ctx = ContextManager(budget=1000, llm=llm, keep_recent_tokens=100,
                         results_dir=bridge.results_dir())
    msgs = [_msg("user", "x" * 300) for _ in range(20)]
    ctx.prepare(msgs)  # 触发压缩 → pending_compaction
    bridge.write_compaction(ctx)
    assert session.compaction_floor is not None
    cache_entries = [e for e in session.tree.entries.values() if e.type == "compaction"]
    assert len(cache_entries) == 1
    # restore：新 ctx 从 session 恢复（免重算）
    ctx2 = ContextManager(budget=1000, llm=FakeLLM(), keep_recent_tokens=100,
                          results_dir=bridge.results_dir())
    bridge.restore_cache(ctx2)
    assert ctx2._summary is not None
    assert ctx2._covered_count == ctx._covered_count
    assert ctx2._retained_tail == ctx._retained_tail