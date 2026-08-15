"""skill 机制：数据模型 + 仓储发现 + 格式化（pig-mono 式三件套，模型侧无 read 工具）。

SkillManager 为 Repository 形态：持有 dict 状态，构造即发现，查询/格式化全部
收编为实例方法（对应 pig-mono 的 SkillManager 类；模块级函数版本见历史）。
"""
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


class SkillManager:
    """skill 仓储（Repository）：发现 + 按名索引 + 清单/调用文本生成。

    发现规则（pig-mono 同款）：只扫每个来源目录的一层子目录，认 <name>/SKILL.md；
    name = 目录名（不读 frontmatter name）。缺 description → 跳过该 skill。
    隐藏目录（. 开头）跳过。目录不存在 → 静默跳过。容错全静默，不抛不告警。
    """

    def __init__(self, dirs: list[str | Path] | None = None):
        """构造即发现：None → 探测 <cwd>/.agents/skills（不存在 → 空，静默）；
        [] → 显式禁用；非空 list → 只扫这些目录。"""
        self.skills: dict[str, Skill] = {}
        if dirs is None:
            dirs = [Path.cwd() / ".agents" / "skills"]
        for root in dirs:
            self._discover_dir(Path(root))

    def _discover_dir(self, root: Path) -> None:
        """扫单一来源目录的一层子目录（不递归、不认根级 .md、跳过隐藏目录）。"""
        if not root.is_dir():
            return
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            skill = self._load_one(skill_file)
            if skill is not None:
                self.skills[skill.name] = skill

    def _load_one(self, path: Path) -> Skill | None:
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

    def get(self, name: str) -> Skill | None:
        """按名查询（Repository 主查询）。"""
        return self.skills.get(name)

    def list(self) -> list[Skill]:
        """全部 skills，发现顺序。"""
        return list(self.skills.values())

    def __len__(self) -> int:
        return len(self.skills)

    def __contains__(self, name: str) -> bool:
        return name in self.skills

    def format_prompt(self, names: list[str] | None = None) -> str:
        """全部（或指定名字子集）skills → XML 清单块；空 → 空串（进 system）。
        names 给定只格式化这些名字（供 subagent skills 字段取子集）；未知名忽略。"""
        skills = (self.skills[n] for n in names if n in self.skills) if names is not None \
            else self.skills.values()
        parts = ["<available_skills>"]
        for s in skills:
            parts.append("  <skill>")
            parts.append(f"    <name>{s.name}</name>")
            parts.append(f"    <description>{s.description}</description>")
            parts.append("  </skill>")
        if len(parts) == 1:
            return ""
        parts.append("</available_skills>")
        return "\n".join(parts)

    def format_invocation(self, name: str, instructions: str = "") -> str:
        """按名取正文并包装 '<skill name="…" location="…">\\n{content}\\n</skill>'
        + 可选附言（\\n\\n 衔接）。未知名 → ValueError（列可用名字）。"""
        skill = self.get(name)
        if skill is None:
            available = ", ".join(sorted(self.skills)) or "(none)"
            raise ValueError(f"Unknown skill '{name}'. Available: {available}")
        block = (f'<skill name="{skill.name}" location="{skill.file_path}">\n'
                 f"{skill.content}\n</skill>")
        return f"{block}\n\n{instructions}" if instructions else block