"""skill 机制离线测试（skills.py 数据模型 + frontmatter 解析，不碰真网络）。"""
from pathlib import Path

import pytest

from my_agent_llm import Response

from my_agent_core.agent import Agent
from my_agent_core.skills import Skill, format_skill_invocation, format_skills_for_prompt, load_skills, parse_frontmatter
from my_agent_core.tools import tool


class FakeLLM:
    """替身（与 test_agent.py 同款的最小版）：按脚本返回 Response。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages), "tools": tools})
        return self.responses.pop(0)


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


def _response(content: str = "") -> Response:
    return Response(content=content, model="fake")


def test_parse_frontmatter_basic():
    """有 frontmatter：字段 dict + body 分离，body 前后 trim（#1）。"""
    text = "---\nname: foo\ndescription: bar\n---\n\nbody text\n"
    meta, body = parse_frontmatter(text)
    assert meta == {"name": "foo", "description": "bar"}
    assert body == "body text"


def test_parse_frontmatter_no_frontmatter():
    """无 frontmatter（不以 --- 开头）→ ({}, 全文)。"""
    assert parse_frontmatter("plain text") == ({}, "plain text")


def test_parse_frontmatter_multiline_literal_block():
    """多行 | 块完整读取（PyYAML 的卖点）。"""
    text = '---\ndescription: |\n  line one\n  line two\n---\nbody'
    meta, body = parse_frontmatter(text)
    assert meta["description"] == "line one\nline two"


def test_parse_frontmatter_unknown_keys_ignored():
    """未知键保留在 dict（读取方只取 description，此处仅验证不报错）。"""
    meta, _ = parse_frontmatter("---\ndescription: d\nfoo: 1\n---\nbody")
    assert meta["description"] == "d"


def test_parse_frontmatter_bad_yaml_degrades():
    """坏 YAML（不成对方括号）→ ({}, 全文) 静默降级，不抛。"""
    text = "---\ndescription: [unclosed\n---\nbody"
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert body == text


def _write_skill(root: Path, name: str, description: str = "desc", content: str = "body") -> Path:
    """helper：在 root/name/SKILL.md 写一个标准 skill，返回 SKILL.md 路径。"""
    d = root / name
    d.mkdir(parents=True)
    p = d / "SKILL.md"
    p.write_text(f"---\ndescription: {description}\n---\n\n{content}", encoding="utf-8")
    return p


def test_load_skills_basic(tmp_path):
    """只认 <dir>/SKILL.md；name=目录名；description 来自 frontmatter（#2 #3）。"""
    _write_skill(tmp_path, "code-review", description="review code", content="checklist")
    skills = load_skills([tmp_path])
    assert len(skills) == 1
    assert skills[0].name == "code-review"
    assert skills[0].description == "review code"
    assert skills[0].content == "checklist"


def test_load_skills_ignores_non_skill_files(tmp_path):
    """根级 .md / 非 SKILL.md 文件 / 无 SKILL.md 的子目录 / 其他文件 → 全部忽略（#2）。"""
    (tmp_path / "quick-notes.md").write_text("x")          # 根级 .md
    (tmp_path / "SKILL.md").write_text("x")                 # 根级 SKILL.md
    (tmp_path / "no-skill").mkdir()                          # 无 SKILL.md 的目录
    (tmp_path / "notes.py").write_text("x")                 # 其他文件
    assert load_skills([tmp_path]) == []


def test_load_skills_no_recursion(tmp_path):
    """不递归：子目录里的 SKILL.md 不算（#2）。"""
    sub = tmp_path / "parent" / "child"
    sub.mkdir(parents=True)
    (sub / "SKILL.md").write_text("x")
    assert load_skills([tmp_path]) == []


def test_load_skills_skips_hidden_dirs(tmp_path):
    """隐藏目录（. 开头）跳过（#2）。"""
    _write_skill(tmp_path, ".hidden")
    _write_skill(tmp_path, "visible")
    skills = load_skills([tmp_path])
    assert [s.name for s in skills] == ["visible"]


def test_load_skills_missing_skips(tmp_path):
    """缺 description → 跳过该 skill；目录不存在 → 静默空（#4）。"""
    d = tmp_path / "code-review"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: cr\n---\nbody", encoding="utf-8")  # 只有 name 没 description
    assert load_skills([tmp_path]) == []
    assert load_skills([tmp_path / "nope"]) == []


def test_format_skills_for_prompt_structure(tmp_path):
    """XML 清单：结构逐行正确；空列表 → 空串（#5）。"""
    skills = [Skill(name="code-review", description="review code",
                    content="checklist", file_path=tmp_path / "code-review" / "SKILL.md"),
              Skill(name="pdf", description="process pdf",
                    content="steps", file_path=tmp_path / "pdf" / "SKILL.md")]
    out = format_skills_for_prompt(skills)
    assert out.splitlines() == [
        "<available_skills>",
        "  <skill>",
        "    <name>code-review</name>",
        "    <description>review code</description>",
        "  </skill>",
        "  <skill>",
        "    <name>pdf</name>",
        "    <description>process pdf</description>",
        "  </skill>",
        "</available_skills>",
    ]
    assert format_skills_for_prompt([]) == ""


def test_format_skill_invocation(tmp_path):
    """<skill name location> 包装 + 可选附言（\\n\\n 衔接）；无附言时纯 block（#6）。"""
    skill = Skill(name="code-review", description="d",
                  content="checklist", file_path=tmp_path / "code-review" / "SKILL.md")
    out = format_skill_invocation(skill, "重点看并发")
    assert out == ('<skill name="code-review" location="' + str(tmp_path / "code-review" / "SKILL.md") +
                   '">\nchecklist\n</skill>\n\n重点看并发')
    assert format_skill_invocation(skill) == ('<skill name="code-review" location="' +
                                              str(tmp_path / "code-review" / "SKILL.md") +
                                              '">\nchecklist\n</skill>')


def test_agent_assembles_with_skills(tmp_path, monkeypatch):
    """skill_dirs → system 含清单块、agent.skills 正确、tools 不变（#7）。"""
    _write_skill(tmp_path, "code-review", description="review code", content="checklist")
    llm = FakeLLM([_response(content="ok")])
    agent = Agent(llm=llm, tools=[multiply], skill_dirs=[tmp_path])
    assert [s.name for s in agent.skills] == ["code-review"]
    agent.run("hi")  # 触发 llm.chat 才能看到 tools/messages
    first = llm.calls[0]["messages"][0]
    assert first.role == "system"
    assert "<available_skills>" in first.content
    assert "<name>code-review</name>" in first.content
    # tools 不变：只有用户给的 multiply，无 read_skill
    assert llm.calls[0]["tools"] == [t.to_openai_schema() for t in [multiply]]


def test_agent_skill_dirs_none_no_default_dir(tmp_path, monkeypatch):
    """skill_dirs=None（默认）→ 探测 cwd/.agents/skills；目录不存在 → skills 空、
    无清单块、tools 不变；既有行为保持（#7 回归）。"""
    monkeypatch.chdir(tmp_path)  # 干净的 cwd，无 .agents/skills → 探测结果空
    llm = FakeLLM([_response(content="ok")])
    agent = Agent(llm=llm, tools=[multiply], system_prompt="sys")
    assert agent.skills == []
    agent.run("hi")
    assert llm.calls[0]["messages"][0].content == "sys"
    assert llm.calls[0]["tools"] == [t.to_openai_schema() for t in [multiply]]


def test_agent_skill_dirs_none_probes_default(tmp_path, monkeypatch):
    """skill_dirs=None 且 <cwd>/.agents/skills 存在 → 自动加载（#7，pig-mono 式默认）。"""
    _write_skill(tmp_path / ".agents" / "skills", "probe", description="p", content="c")
    monkeypatch.chdir(tmp_path)
    llm = FakeLLM([_response(content="ok")])
    agent = Agent(llm=llm, tools=[multiply])
    assert [s.name for s in agent.skills] == ["probe"]


def test_agent_skill_dirs_empty_list_no_probe(tmp_path, monkeypatch):
    """skill_dirs=[] 显式空 → 不探测、无 skill（区别于 None 的默认探测）。"""
    monkeypatch.chdir(tmp_path)
    llm = FakeLLM([_response(content="ok")])
    agent = Agent(llm=llm, tools=[multiply], skill_dirs=[])
    assert agent.skills == []


def test_invoke_skill(tmp_path):
    """invoke_skill：追加 user 消息 = <skill>包装 + 附言；未知名字 → ValueError（#8）。"""
    _write_skill(tmp_path, "code-review", description="review code", content="checklist")
    llm = FakeLLM([_response(content="done")])
    agent = Agent(llm=llm, tools=[multiply], skill_dirs=[tmp_path])
    answer = agent.invoke_skill("code-review", "重点看并发")
    assert answer == "done"
    last_msg = llm.calls[0]["messages"][-1]
    assert last_msg.role == "user"
    assert last_msg.content.startswith('<skill name="code-review"')
    assert "checklist" in last_msg.content
    assert "重点看并发" in last_msg.content
    # 未知名字 → ValueError（列可用名字）
    with pytest.raises(ValueError, match="code-review"):
        agent.invoke_skill("nope")


def test_load_skills_with_bom(tmp_path):
    """SKILL.md 带 UTF-8 BOM → 正常加载（utf-8-sig 兼容）。"""
    d = tmp_path / "code-review"
    d.mkdir()
    p = d / "SKILL.md"
    p.write_bytes("﻿---\ndescription: review code\n---\n\nbody".encode("utf-8"))
    skills = load_skills([tmp_path])
    assert len(skills) == 1
    assert skills[0].name == "code-review"
    assert skills[0].description == "review code"