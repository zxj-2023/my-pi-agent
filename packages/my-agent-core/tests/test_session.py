"""SessionTree 树结构测试（会话设计文档 §8 #1–#3）。"""
import json
from pathlib import Path

from my_agent_core.agent import Agent
from my_agent_core.session import Session, SessionTree
from my_agent_core.tools import tool
from my_agent_llm import Message, Response


def test_tree_first_entry_is_root():
    """首个 entry 成为根，current 指向它（#1）。"""
    tree = SessionTree()
    e = tree.add_entry("user", "hi")
    assert tree.root_id == e.id
    assert tree.current_id == e.id
    assert e.parent_id is None
    assert e.role == "user"
    assert e.content == "hi"


def test_tree_path_root_to_current():
    """多 entry 后 get_current_path = 根→current 完整路径（#2）。"""
    tree = SessionTree()
    tree.add_entry("user", "q1")
    tree.add_entry("assistant", "a1")
    tree.add_entry("user", "q2")
    path = tree.get_current_path()
    assert [e.content for e in path] == ["q1", "a1", "q2"]
    assert path[0].id == tree.root_id
    assert path[-1].id == tree.current_id


def test_tree_rewind_keeps_old_branch():
    """rewind 移动 current 指针，旧分支 entry 仍在树里；rewind 后长新枝 parent 正确（#3）。"""
    tree = SessionTree()
    tree.add_entry("user", "q1")
    a = tree.add_entry("assistant", "a1")
    tree.add_entry("user", "q2")
    tree.rewind(a.id)
    assert tree.current_id == a.id
    assert len(tree.entries) == 3  # 旧分支保留
    assert [e.content for e in tree.get_current_path()] == ["q1", "a1"]
    # rewind 后继续 → 在 a1 下长新枝
    b = tree.add_entry("user", "q2-prime")
    assert b.parent_id == a.id
    assert [e.content for e in tree.get_current_path()] == ["q1", "a1", "q2-prime"]
    assert "q2" in [e.content for e in tree.entries.values()]  # 旧枝完整保留


def test_tree_rewind_missing_entry_raises():
    """rewind 到不存在的 entry 抛 ValueError（设计文档 §7）。"""
    tree = SessionTree()
    tree.add_entry("user", "hi")
    try:
        tree.rewind("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_save_load_round_trip(tmp_path):
    """加几条消息 → save → load → 树全等（entries 数、current/root）（#4）。"""
    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    session.add_message("assistant", "a1")
    loaded = Session.load(session.path)
    assert len(loaded.tree.entries) == 2
    assert loaded.tree.root_id == session.tree.root_id
    assert loaded.tree.current_id == session.tree.current_id
    assert [e.content for e in loaded.tree.get_current_path()] == ["q1", "a1"]


def test_messages_round_trip_with_metadata(tmp_path):
    """get_current_path_messages → list[Message]，tool_calls/tool_call_id 在 metadata（#5）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    session.add_message("assistant", "", tool_calls=tc)
    session.add_message("tool", "42", tool_call_id="1")
    msgs = session.get_current_path_messages()
    assert [m.role for m in msgs] == ["user", "assistant", "tool"]
    assert msgs[1].metadata["tool_calls"] == tc
    assert msgs[2].metadata["tool_call_id"] == "1"
    # Message 往返：model_dump → model_validate 一致
    assert msgs[0] == Message.model_validate(msgs[0].model_dump())


def test_atomic_write_tmp_remnant_does_not_break(tmp_path):
    """save 后文件完整；目录里残留损坏 tmp 文件不影响加载（#6）。"""
    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    (tmp_path / ".s.jsonl.abc.tmp").write_text("garbage", encoding="utf-8")
    loaded = Session.load(session.path)
    assert [e.content for e in loaded.tree.get_current_path()] == ["q1"]


def test_atomic_write_failure_keeps_snapshot(tmp_path, monkeypatch):
    """写中断（os.replace 抛错）→ 上次快照不被破坏（#6）。"""
    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    snapshot = session.path.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("my_agent_core.session.os.replace", boom)
    try:
        session.add_message("user", "q2")
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")
    assert session.path.read_text(encoding="utf-8") == snapshot  # 快照未变


def test_load_tolerates_torn_last_line(tmp_path):
    """尾行撕裂（不完整 JSON）→ 丢弃该行，其余正常加载（设计文档 §7）。"""
    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    session.add_message("assistant", "a1")
    with open(session.path, "a", encoding="utf-8") as f:
        f.write('{"id":"zz","parent_id"')  # 撕裂尾行
    loaded = Session.load(session.path)
    assert [e.content for e in loaded.tree.get_current_path()] == ["q1", "a1"]


class FakeLLM:
    """替身（同 test_agent.py）：chat 按脚本返回 Response，记录收到的 messages。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages)})
        return self.responses.pop(0)


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


def _response(content: str = "", tool_calls=None) -> Response:
    return Response(content=content, model="fake", tool_calls=tool_calls)


def test_agent_persists_file_line_order(tmp_path):
    """Agent + Session 跑一轮 → 文件行序：header, user, assistant(tool_calls), tool, assistant（#7）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 6, "b": 7}'}}]
    llm = FakeLLM([_response(tool_calls=tc), _response(content="42")])
    session = Session(path=tmp_path / "s.jsonl")
    agent = Agent(llm=llm, tools=[multiply], session=session)
    agent.run("compute")
    lines = session.path.read_text(encoding="utf-8").strip().splitlines()
    roles = [json.loads(ln)["role"] for ln in lines[1:]]
    assert roles == ["user", "assistant", "tool", "assistant"]
    # assistant(tool_calls) 行的 metadata 带 tool_calls
    assert "tool_calls" in json.loads(lines[2])["metadata"]


def test_second_agent_resumes_history(tmp_path):
    """第一 Agent 跑完 → Session.load 恢复 → 第二 Agent 首次请求 messages 含全部历史（#8）。"""
    tc = [{"id": "1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 6, "b": 7}'}}]
    llm1 = FakeLLM([_response(tool_calls=tc), _response(content="42")])
    session = Session(path=tmp_path / "s.jsonl")
    Agent(llm=llm1, tools=[multiply], session=session).run("compute")
    # “进程 2”：从文件恢复，而不是复用内存对象
    restored = Session.load(session.path)
    llm2 = FakeLLM([_response(content="ok")])
    agent2 = Agent(llm=llm2, tools=[multiply], session=restored)
    agent2.run("再乘2呢")
    first = llm2.calls[0]["messages"]
    assert [m.role for m in first] == ["user", "assistant", "tool", "assistant", "user"]
    assert first[-1].content == "再乘2呢"


def test_rewind_then_run_grows_new_branch(tmp_path):
    """session.rewind 后 agent.run → 新消息从回退点长新枝（parent 正确）（#9）。"""
    llm1 = FakeLLM([_response(content="42")])
    session = Session(path=tmp_path / "s.jsonl")
    agent = Agent(llm=llm1, tools=[multiply], session=session)
    agent.run("q1")
    q1_entry = next(e for e in session.tree.entries.values() if e.role == "user" and e.content == "q1")
    session.rewind(q1_entry.id)
    llm2 = FakeLLM([_response(content="另答")])
    agent2 = Agent(llm=llm2, tools=[multiply], session=session)
    agent2.run("换个问法")
    new_user = next(e for e in session.tree.entries.values() if e.role == "user" and e.content == "换个问法")
    assert new_user.parent_id == q1_entry.id  # 从回退点长新枝
    assert [e.content for e in session.tree.get_current_path()] == ["q1", "换个问法", "另答"]
    # 旧枝保留
    assert "42" in [e.content for e in session.tree.entries.values()]


def test_persistent_agent_reset(tmp_path):
    """持久化 Agent reset → 树清空、文件重写为 header（纯对话）（#10）。"""
    llm = FakeLLM([_response(content="hi")])
    session = Session(path=tmp_path / "s.jsonl")
    agent = Agent(llm=llm, tools=[multiply], session=session)
    agent.run("q1")
    agent.reset()
    lines = session.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1  # 仅 header
    assert [e.role for e in session.tree.entries.values()] == []
    assert agent.messages == []


def test_resume_uses_new_system_prompt(tmp_path):
    """session 不含 system：恢复后 Agent 用传入的 system_prompt 拼 system。"""
    llm1 = FakeLLM([_response(content="hi")])
    session = Session(path=tmp_path / "s.jsonl")
    Agent(llm=llm1, tools=[multiply], session=session, system_prompt="旧system").run("q1")
    restored = Session.load(session.path)
    llm2 = FakeLLM([_response(content="ok")])
    agent2 = Agent(llm=llm2, tools=[multiply], session=restored, system_prompt="新system")
    agent2.run("q2")
    first = llm2.calls[0]["messages"]
    sys_msgs = [m for m in first if m.role == "system"]
    assert len(sys_msgs) == 1
    assert sys_msgs[0].content == "新system"      # 不再是「文件里的 system」，而是新传入的


def test_rewind_then_same_agent_run_syncs_context(tmp_path):
    """同一 Agent：session.rewind 后 run → LLM 收到的 messages 从回退点开始（不含旧分支尾）。"""
    llm1 = FakeLLM([_response(content="42")])
    session = Session(path=tmp_path / "s.jsonl")
    agent = Agent(llm=llm1, tools=[multiply], session=session, system_prompt="sys")
    agent.run("q1")
    q1_entry = next(e for e in session.tree.entries.values() if e.role == "user" and e.content == "q1")
    session.rewind(q1_entry.id)
    llm2 = FakeLLM([_response(content="另答")])
    agent.llm = llm2  # 同一 Agent 实例续跑
    agent.run("换个问法")
    first = llm2.calls[0]["messages"]
    assert [m.role for m in first] == ["system", "user", "user"]  # 从回退点开始，旧分支尾不在
    assert [m.content for m in first] == ["sys", "q1", "换个问法"]


def test_load_rejects_header_missing_id(tmp_path):
    """header 缺必要字段（非会话文件）→ ValueError（type/version 门禁已删，改按必要字段校验）。"""
    p = tmp_path / "not-session.jsonl"
    p.write_text('{"foo": "bar"}\n', encoding="utf-8")
    try:
        Session.load(p)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_entry_type_defaults_to_message(tmp_path):
    """SessionEntry 默认 type='message'；save 时普通消息不写 type 字段（exclude_defaults）（context §4.3）。"""
    import json as _json

    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    lines = session.path.read_text(encoding="utf-8").strip().splitlines()
    entry = _json.loads(lines[-1])
    assert "type" not in entry  # 普通消息不写默认值
    assert session.tree.entries[entry["id"]].type == "message"


def test_add_summary_cache_does_not_move_current(tmp_path):
    """add_summary_cache 插入 type='compaction' entry，不动 current_id，floor 持久化（context §4.3/§5）。"""
    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    session.add_message("assistant", "a1")
    current_before = session.tree.current_id
    session.add_summary_cache(
        "## Goal ...", covered_count=2,
        retained_tail=[{"role": "assistant", "content": "a1"}],
        tokens_before=95000, summary_model="fake",
    )
    assert session.tree.current_id == current_before  # 不动 current
    cache_entries = [e for e in session.tree.entries.values() if e.type == "compaction"]
    assert len(cache_entries) == 1
    assert cache_entries[0].metadata["covered_count"] == 2
    assert session.compaction_floor == current_before
    # floor 持久化
    loaded = Session.load(session.path)
    assert loaded.compaction_floor == current_before


def test_full_history_filters_compaction(tmp_path):
    """get_full_history_messages 排除 type='compaction' 节点（context §4.3）。"""
    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    session.add_message("assistant", "a1")
    session.add_summary_cache("## Goal", covered_count=2, retained_tail=[{"role": "assistant", "content": "a1"}], tokens_before=10)
    msgs = session.get_full_history_messages()
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert all("[Context summary" not in m.content for m in msgs)


def test_rewind_guard_blocks_pre_floor(tmp_path):
    """压缩后 rewind 到 floor 之前 → ValueError；floor 之后新枝 → 允许（context §5）。"""
    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    a1 = session.add_message("assistant", "a1")
    session.add_message("user", "q2")  # floor 将设在这里
    session.add_summary_cache("## Goal", covered_count=2,
                              retained_tail=[{"role": "user", "content": "q2"}], tokens_before=10)
    # floor 之后的新消息
    new_entry = session.add_message("user", "q3")
    assert new_entry.id is not None
    # rewind 回旧段（q1）→ ValueError
    try:
        session.rewind(a1.id)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError (rewind before floor)")
    # rewind 到 floor 本身 → 允许
    session.rewind(session.compaction_floor)
    assert session.tree.current_id == session.compaction_floor


def test_rewind_guard_after_reset(tmp_path):
    """reset 清 floor → rewind 恢复自由（context §5）。"""
    session = Session(path=tmp_path / "s.jsonl")
    session.add_message("user", "q1")
    session.add_summary_cache("## Goal", covered_count=1, retained_tail=[{"role": "assistant", "content": "a1"}], tokens_before=10)
    session.reset()
    assert session.compaction_floor is None
    # reset 后树为空；新消息入树后 rewind 不受旧 floor 限制
    e1 = session.add_message("user", "q2")
    session.add_message("assistant", "a2")
    session.rewind(e1.id)  # 不抛