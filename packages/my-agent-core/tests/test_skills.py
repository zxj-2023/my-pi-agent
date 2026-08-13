"""skill 机制离线测试（skills.py 数据模型 + frontmatter 解析，不碰真网络）。"""
from pathlib import Path

from my_agent_core.skills import Skill, load_skills, parse_frontmatter


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