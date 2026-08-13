"""skill 机制离线测试（skills.py 数据模型 + frontmatter 解析，不碰真网络）。"""
from my_agent_core.skills import Skill, parse_frontmatter


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