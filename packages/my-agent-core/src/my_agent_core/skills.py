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