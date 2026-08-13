"""skill 机制：数据模型 + 发现 + 格式化（pig-mono 式三件套，模型侧无 read 工具）。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Skill:
    """一个技能：name 来自目录名，description 来自 frontmatter，content 是正文。"""

    name: str
    description: str
    content: str                     # frontmatter 之下的正文
    file_path: Path                  # 调试用；不暴露给模型


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """首部 --- 换行 YAML 换行 --- → (字段 dict, body)。无 frontmatter → ({}, 全文)。
    用 yaml.safe_load；坏 YAML → 降级 ({}, 全文)，不抛不告警。"""
    header = "---\n"
    if not text.startswith(header):
        return {}, text
    end = text.find("\n---\n", len(header))
    if end == -1:
        return {}, text
    block = text[len(header):end]
    body = text[end + len("\n---\n"):].strip()
    try:
        fields = yaml.safe_load(block)
    except yaml.YAMLError:
        return {}, text
    if not isinstance(fields, dict):
        return {}, text
    return {str(k): str(v) for k, v in fields.items()}, body


def load_skills(dirs: list[str | Path] | None) -> list[Skill]:
    """发现 + 解析，容错静默。只扫每个来源目录的一层子目录，认 <name>/SKILL.md；
    name = 目录名（不读 frontmatter name）。缺 description → 跳过该 skill。
    隐藏目录（. 开头）跳过。目录不存在 → 静默跳过。
    dirs 为 None → 探测 <cwd>/.agents/skills（不存在 → 空，静默）；
    dirs 为 [] → 显式禁用，直接返回空（区别于 None 的默认探测）。"""
    if dirs is None:
        dirs = [Path.cwd() / ".agents" / "skills"]
    skills: list[Skill] = []
    for root in dirs:
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        for child in sorted(root_path.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            skill = _load_one(skill_file)
            if skill is not None:
                skills.append(skill)
    return skills


def _load_one(path: Path) -> Skill | None:
    """读单个 SKILL.md → Skill；任何失败/缺 description → None（静默）。"""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    meta, body = parse_frontmatter(text)
    description = meta.get("description")
    if not description:
        return None
    return Skill(name=path.parent.name, description=description,
                 content=body, file_path=path)


def format_skills_for_prompt(skills: list[Skill]) -> str:
    """全部 skills → XML 清单块；空 → 空串。仅告知存在与 description
    （模型无自助取正文通道，取正文靠宿主 invoke_skill）。"""
    if not skills:
        return ""
    parts = ["<available_skills>"]
    for s in skills:
        parts.append("  <skill>")
        parts.append(f"    <name>{s.name}</name>")
        parts.append(f"    <description>{s.description}</description>")
        parts.append("  </skill>")
    parts.append("</available_skills>")
    return "\n".join(parts)


def format_skill_invocation(skill: Skill, instructions: str = "") -> str:
    """'<skill name="…" location="…">\\n{content}\\n</skill>' + 可选附言（\\n\\n 衔接，同 pi）。"""
    block = (f'<skill name="{skill.name}" location="{skill.file_path}">\n'
             f"{skill.content}\n</skill>")
    return f"{block}\n\n{instructions}" if instructions else block