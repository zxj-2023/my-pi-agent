"""subagent 机制离线测试（数据模型 + 发现 + 清单，不碰真网络）。"""
import tempfile
from pathlib import Path

import pytest

from my_agent_llm import Response

from my_agent_core.agent import Agent
from my_agent_core.session import Session
from my_agent_core.subagents import DEFAULT_SUBAGENT, Subagent, SubagentManager
from my_agent_core.tools import tool
from my_agent_core.tools.builtin import make_task_tool


def _write_agent(root: Path, name: str, description: str = "desc",
                 content: str = "body", extra: str = "") -> Path:
    """helper：在 root/<name>.md 写一个标准化 agent（扁平文件式）。"""
    p = root / f"{name}.md"
    p.write_text(f"---\ndescription: {description}\n{extra}---\n\n{content}", encoding="utf-8")
    return p


def test_load_basic(tmp_path):
    """只认 <dir>/*.md；name=frontmatter name；description/正文正确（#1）。"""
    _write_agent(tmp_path, "code-reviewer", description="review code", content="checklist")
    skills = SubagentManager([tmp_path]).list()
    assert len(skills) == 1
    assert skills[0].name == "code-reviewer"
    assert skills[0].description == "review code"
    assert skills[0].content == "checklist"


def test_name_falls_back_to_stem(tmp_path):
    """无 name 键 → name=文件 stem；缺 description → 跳过（#2）。"""
    p = tmp_path / "reviewer.md"
    p.write_text("---\ndescription: d\n---\nbody", encoding="utf-8")
    (tmp_path / "nobody.md").write_text("---\nname: x\n---\nbody", encoding="utf-8")  # 缺 description
    skills = SubagentManager([tmp_path]).list()
    assert [s.name for s in skills] == ["reviewer"]


def test_ignores_non_md_and_readme(tmp_path):
    """非 .md / README.md / 子目录 .md → 全部忽略（#3）。"""
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "README.md").write_text("---\ndescription: d\n---\nbody")
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "inner.md").write_text("---\ndescription: d\n---\nbody")
    assert SubagentManager([tmp_path]).list() == []


def test_frontmatter_camelcase_map(tmp_path):
    """camelCase 键映射：maxTurns/disallowedTools/skills/tools/model/effort（#4）。"""
    _write_agent(tmp_path, "full", description="d", content="body",
                 extra="model: sonnet\neffort: high\nmaxTurns: 20\n")
    _write_agent(tmp_path, "lists", description="d", content="body",
                 extra="tools: read, write\ndisallowedTools: bash\nskills: a, b\n")
    skills = {s.name: s for s in SubagentManager([tmp_path]).list()}
    full = skills["full"]
    assert full.model == "sonnet"
    assert full.effort == "high"
    assert full.max_turns == 20
    assert full.tools is None
    assert full.disallowed_tools == ()
    lists = skills["lists"]
    assert lists.tools == ("read", "write")
    assert lists.disallowed_tools == ("bash",)
    assert lists.skills == ("a", "b")


def test_load_bad_yaml_and_bom(tmp_path):
    """坏 YAML → 静默跳过；BOM → 正常加载（#5）。"""
    (tmp_path / "bad.md").write_text("---\ndescription: [unclosed\n---\nbody", encoding="utf-8")
    d = tmp_path / "bom.md"
    d.write_bytes("---\ndescription: review\n---\n\nbody".encode("utf-8-sig"))
    skills = SubagentManager([tmp_path]).list()
    assert [s.name for s in skills] == ["bom"]


def test_default_is_module_constant_not_indexed(tmp_path):
    """DEFAULT_SUBAGENT 是模块常量；空 manager 不含它（不进索引/清单）。"""
    manager = SubagentManager([])
    assert manager.get("default") is None
    assert len(manager) == 0
    assert manager.format_prompt() == ""
    assert DEFAULT_SUBAGENT.name == "default"
    assert DEFAULT_SUBAGENT.content.startswith("You are a subagent.")


class FakeLLM:
    """替身：按脚本返回 Response，记录 messages/tools/kwargs。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        return self.responses.pop(0)


def _response(content: str = "", tool_calls=None) -> Response:
    return Response(content=content, model="fake", tool_calls=tool_calls)


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool
def get_time() -> str:
    """Get the current time."""
    return "12:00"


def _task_call(prompt: str, agent_type: str = "code-reviewer") -> dict:
    import json
    return {"id": "1", "type": "function",
            "function": {"name": "task",
                         "arguments": json.dumps({"prompt": prompt, "agent_type": agent_type})}}


def _parent(manager, llm, tools=(multiply, get_time)):
    """构造父 Agent 并手动装配 task 工具（Task 4 前暂不自动装配）。"""
    agent = Agent(llm=llm, tools=list(tools),
                  session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"))
    agent.registry.register(make_task_tool(manager, agent))
    return agent


def test_task_delegates_and_isolates(tmp_path):
    """委派：父调 task → 子 Fresh context 跑 → 父收子最终文本（#6 #7）。"""
    _write_agent(tmp_path, "code-reviewer", description="review code",
                 content="You are a reviewer.")
    manager = SubagentManager([tmp_path])
    llm = FakeLLM([
        _response(tool_calls=[_task_call("review this", "code-reviewer")]),
        _response(content="found 3 issues"),   # 子代理最终文本
        _response(content="done"),             # 父最终
    ])
    agent = _parent(manager, llm)
    answer = agent.run("delegate")
    assert answer == "done"
    # 子代理 fresh context：call[1] = system(子正文) + user(prompt)，无父历史
    sub_msgs = llm.calls[1]["messages"]
    assert sub_msgs[0].role == "system"
    assert "You are a reviewer." in sub_msgs[0].content
    assert sub_msgs[-1].role == "user"
    assert sub_msgs[-1].content == "review this"
    assert not any(m.content == "delegate" for m in sub_msgs)


def test_subagent_tool_filtering(tmp_path):
    """tools 白名单/黑名单过滤 + task 永不出现（#8）。"""
    _write_agent(tmp_path, "limited", description="d", content="body",
                 extra="tools: multiply\ndisallowedTools: get_time\n")
    manager = SubagentManager([tmp_path])
    llm = FakeLLM([
        _response(tool_calls=[_task_call("go", "limited")]),
        _response(content="sub done"),
        _response(content="parent done"),
    ])
    agent = _parent(manager, llm)
    agent.run("delegate")
    sub_tool_names = [t["function"]["name"] for t in llm.calls[1]["tools"]]
    assert sub_tool_names == ["multiply"]      # 只剩白名单（get_time 被黑名单 + 白名单共同剔除）


def test_subagent_no_task_tool_even_whitelisted(tmp_path):
    """白名单显式含 task 也被剔除（防递归）。"""
    _write_agent(tmp_path, "recursive", description="d", content="body",
                 extra="tools: multiply, task\n")
    manager = SubagentManager([tmp_path])
    llm = FakeLLM([
        _response(tool_calls=[_task_call("go", "recursive")]),
        _response(content="sub done"),
        _response(content="parent done"),
    ])
    agent = _parent(manager, llm)
    agent.run("delegate")
    sub_tool_names = [t["function"]["name"] for t in llm.calls[1]["tools"]]
    assert sub_tool_names == ["multiply"]


def test_child_does_not_reprobe_subagent_dirs(tmp_path, monkeypatch):
    """防递归：cwd 有 .agents/agents 时，子代理仍不重新装配 task（subagent_dirs=[] 禁用再探测）。"""
    d = tmp_path / ".agents" / "agents"
    d.mkdir(parents=True)
    _write_agent(d, "code-reviewer", description="review code", content="body")
    monkeypatch.chdir(tmp_path)
    manager = SubagentManager()  # 探测 cwd/.agents/agents → 找到 code-reviewer
    llm = FakeLLM([
        _response(tool_calls=[_task_call("go", "code-reviewer")]),
        _response(content="sub done"),
        _response(content="parent done"),
    ])
    agent = _parent(manager, llm)
    agent.run("delegate")
    sub_tool_names = [t["function"]["name"] for t in llm.calls[1]["tools"]]
    assert "task" not in sub_tool_names


def test_subagent_model_override(tmp_path):
    """子代理收到 model 覆盖（#9）。"""
    _write_agent(tmp_path, "big", description="d", content="body",
                 extra="model: sonnet\nmaxTurns: 5\n")
    manager = SubagentManager([tmp_path])
    llm = FakeLLM([
        _response(tool_calls=[{"id": "1", "type": "function",
                               "function": {"name": "task",
                                            "arguments": '{"prompt": "go", "agent_type": "big"}'}}]),
        _response(content="sub done"),
        _response(content="parent done"),
    ])
    agent = _parent(manager, llm)
    agent.run("delegate")
    assert llm.calls[1]["model"] == "sonnet"


def test_unknown_agent_type_returns_error_string(tmp_path):
    """未知名 agent_type → 错误字符串（列可用名）；父循环继续（#10）。"""
    manager = SubagentManager([tmp_path])
    llm = FakeLLM([
        _response(tool_calls=[_task_call("go", "nope")]),
        _response(content="parent done"),
    ])
    agent = _parent(manager, llm)
    answer = agent.run("delegate")
    assert answer == "parent done"
    tool_msg = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "nope" in tool_msg[0].content
    assert "Unknown subagent" in tool_msg[0].content


def test_default_agent_type_fallback(tmp_path):
    """缺省 agent_type → DEFAULT_SUBAGENT（极简 system、继承父工具、无 task）（#11）。"""
    manager = SubagentManager([tmp_path])
    llm = FakeLLM([
        _response(tool_calls=[_task_call("go", "default")]),
        _response(content="sub done"),
        _response(content="parent done"),
    ])
    agent = _parent(manager, llm)
    agent.run("delegate")
    sub_msgs = llm.calls[1]["messages"]
    assert sub_msgs[0].content.startswith("You are a subagent.")
    sub_tool_names = [t["function"]["name"] for t in llm.calls[1]["tools"]]
    assert set(sub_tool_names) == {"multiply", "get_time"}   # 继承父全部（除 task）
    assert "task" not in sub_tool_names


def test_agent_assembles_subagent_dirs(tmp_path):
    """subagent_dirs → system 含 agent 清单、tools 含 task、原工具保留（#12）。"""
    _write_agent(tmp_path, "code-reviewer", description="review code", content="checklist")
    llm = FakeLLM([_response(content="ok")])
    agent = Agent(llm=llm, tools=[multiply],
                  session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"),
                  subagent_dirs=[tmp_path])
    agent.run("hi")
    first = llm.calls[0]["messages"][0]
    assert first.role == "system"
    assert "<available_agents>" in first.content
    assert "<name>code-reviewer</name>" in first.content
    tool_names = [t["function"]["name"] for t in llm.calls[0]["tools"]]
    assert "task" in tool_names
    assert "multiply" in tool_names


def test_agent_subagent_dirs_none_probes_default(tmp_path, monkeypatch):
    """subagent_dirs=None 且 <cwd>/.agents/agents 存在 → 自动加载（#12）。"""
    d = tmp_path / ".agents" / "agents"
    d.mkdir(parents=True)
    _write_agent(d, "probe", description="p", content="c")
    monkeypatch.chdir(tmp_path)
    llm = FakeLLM([_response(content="ok")])
    agent = Agent(llm=llm, tools=[multiply],
                  session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"))
    agent.run("hi")
    assert [s.name for s in agent.subagent_manager.list()] == ["probe"]


def test_agent_subagent_dirs_empty_disables(tmp_path, monkeypatch):
    """subagent_dirs=[] 显式禁用 → 无 task、无 agent 清单（区别于 None 探测）。"""
    monkeypatch.chdir(tmp_path)
    llm = FakeLLM([_response(content="ok")])
    agent = Agent(llm=llm, tools=[multiply],
                  session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"),
                  subagent_dirs=[])
    agent.run("hi")
    tool_names = [t["function"]["name"] for t in llm.calls[0]["tools"]]
    assert "task" not in tool_names
    assert "<available_agents>" not in llm.calls[0]["messages"][0].content


def test_agent_task_name_conflict_raises(tmp_path):
    """用户自带 name=task 的工具 → ValueError（列冲突）。"""
    _write_agent(tmp_path, "code-reviewer", description="review code", content="checklist")

    @tool(name="task")
    def my_task(prompt: str) -> str:
        """Custom task tool."""
        return prompt

    llm = FakeLLM([_response(content="ok")])
    with pytest.raises(ValueError, match="task"):
        Agent(llm=llm, tools=[multiply, my_task],
              session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"),
              subagent_dirs=[tmp_path])
