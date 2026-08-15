"""subagent 机制离线测试（数据模型 + 发现 + 清单，不碰真网络）。"""
from pathlib import Path

import pytest

from my_agent_core.subagents import (
    DEFAULT_SUBAGENT,
    Subagent,
    SubagentManager,
)


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
