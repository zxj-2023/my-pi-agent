"""subagent 机制：数据模型 + 仓储发现 + 清单格式化（对标 Claude Code 生态 agent 定义）。

SubagentManager 为 Repository 形态（对标 SkillManager）：构造即发现 agents/*.md，
按名索引，清单格式化进 system prompt。委派执行（make_task_tool）见同文件后续部分。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from my_agent_core.skills import parse_frontmatter

if TYPE_CHECKING:
    from my_agent_core.agent import Agent
    from my_agent_core.tools import Tool


@dataclass(frozen=True)
class Subagent:
    """一个子代理定义：name 来自 frontmatter（缺省文件名），description 供主模型
    触发选择，content 是正文（= 子代理 system prompt，不收父 system prompt）。"""

    name: str
    description: str
    content: str
    file_path: Path
    model: str | None = None              # 缺省 inherit = 继承父模型
    effort: str | None = None            # v1 解析但不消费（SDK 无统一 effort 参数，端到端映射留 LLM 层演进）
    max_turns: int | None = None         # maxTurns（缺省继承父 max_iterations）
    tools: tuple[str, ...] | None = None       # 白名单；None=继承父全部
    disallowed_tools: tuple[str, ...] = ()     # 黑名单
    skills: tuple[str, ...] | None = None      # 子代理 skill 名（清单拼 system）


DEFAULT_SUBAGENT_SYSTEM = (
    "You are a subagent. Complete the given task independently, "
    "then summarize your findings."
)
DEFAULT_SUBAGENT = Subagent(
    name="default",
    description="A general-purpose subagent for standalone tasks.",
    content=DEFAULT_SUBAGENT_SYSTEM,
    file_path=Path("<builtin>"),
)


def _split_csv(value: object) -> tuple[str, ...] | None:
    """frontmatter 逗号分隔字符串 → tuple；非字符串/空 → None（保留缺省）。"""
    if not isinstance(value, str):
        return None
    parts = tuple(p.strip() for p in value.split(",") if p.strip())
    return parts if parts else None


def _parse_max_turns(value: object) -> int | None:
    """maxTurns：str 或 int → int；坏值/其他 → None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


class SubagentManager:
    """subagent 仓储：发现 agents/*.md + 按名索引 + 清单格式化。"""

    def __init__(self, dirs: list[str | Path] | None = None):
        """构造即发现：None → 探测 <cwd>/.agents/agents（不存在 → 空，静默）；
        [] → 显式禁用；非空 → 只扫这些目录。"""
        self.subagents: dict[str, Subagent] = {}
        if dirs is None:
            dirs = [Path.cwd() / ".agents" / "agents"]
        for root in dirs:
            self._discover_dir(Path(root))

    def _discover_dir(self, root: Path) -> None:
        """扫一层 *.md（不递归、不认子目录、跳过 README/隐藏文件）。同名后覆盖。"""
        if not root.is_dir():
            return
        for child in sorted(root.iterdir()):
            if child.is_dir() or child.suffix.lower() != ".md":
                continue
            if child.name.startswith(".") or child.name.lower() == "readme.md":
                continue
            sub = self._load_one(child)
            if sub is not None:
                self.subagents[sub.name] = sub

    def _load_one(self, path: Path) -> Subagent | None:
        """读单文件 → Subagent；读失败/坏 YAML/缺 description → None（静默）。"""
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            return None
        meta, body = parse_frontmatter(text)
        description = (meta.get("description") or "").strip()
        if not description:
            return None
        name = (meta.get("name") or "").strip() or path.stem
        return Subagent(
            name=name,
            description=description,
            content=body,
            file_path=path,
            model=meta.get("model") or None,
            effort=meta.get("effort") or None,
            max_turns=_parse_max_turns(meta.get("maxTurns")),
            tools=_split_csv(meta.get("tools")),
            disallowed_tools=_split_csv(meta.get("disallowedTools")) or (),
            skills=_split_csv(meta.get("skills")),
        )

    def get(self, name: str) -> Subagent | None:
        return self.subagents.get(name)

    def list(self) -> list[Subagent]:
        return list(self.subagents.values())

    def __len__(self) -> int:
        return len(self.subagents)

    def __contains__(self, name: str) -> bool:
        return name in self.subagents

    def format_prompt(self) -> str:
        """全部 agents → XML 清单块（名字 + description）；空 → 空串（进 system）。"""
        if not self.subagents:
            return ""
        parts = ["<available_agents>"]
        for s in self.subagents.values():
            parts.append("  <agent>")
            parts.append(f"    <name>{s.name}</name>")
            parts.append(f"    <description>{s.description}</description>")
            parts.append("  </agent>")
        parts.append("</available_agents>")
        return "\n".join(parts)


def _system_for(sub: Subagent, parent: Agent) -> str:
    """子代理 system = 正文 + （若有 skills）子集清单；不收父 system prompt（Claude 官方语义）。
    两段 `\n\n` 衔接，任一为空则跳过（parent 仅用于取 skill_manager）。"""
    parts = [sub.content]
    if sub.skills:
        block = parent.skill_manager.format_prompt(sub.skills)
        if block:
            parts.append(block)
    return "\n\n".join(p for p in parts if p)


def _filter_tools(parent: Agent, sub: Subagent) -> list:
    """父工具集按白/黑名单过滤；task 永不出现（防递归）。"""
    tools = [t for t in parent.registry.list() if t.name != "task"]
    if sub.tools is not None:
        allowed = set(sub.tools)
        tools = [t for t in tools if t.name in allowed]
    black = set(sub.disallowed_tools)
    tools = [t for t in tools if t.name not in black]
    return tools


def make_task_tool(manager: SubagentManager, parent: Agent) -> Tool:
    """产出 `task` 工具：prompt（必需）+ agent_type（可选，缺省 default）。
    执行：查定义 → 过滤工具集 → spawn 子 Agent → run(prompt) → 返回最终文本。
    未知名/子异常 → 错误字符串（不抛）。"""
    from my_agent_core.agent import Agent
    from my_agent_core.tools import Tool

    def task(prompt: str, agent_type: str = "default") -> str:
        """Spawn a subagent with fresh context to complete the given prompt.
        agent_type: name of the subagent definition (see available agents)."""
        sub = manager.get(agent_type)
        if sub is None and agent_type == "default":
            sub = DEFAULT_SUBAGENT
        if sub is None:
            available = ", ".join(sorted(manager.subagents)) or "(none)"
            return f"Unknown subagent '{agent_type}'. Available: {available}"
        try:
            child = Agent(
                llm=parent.llm,
                tools=_filter_tools(parent, sub),
                system_prompt=_system_for(sub, parent),
                model=sub.model,
                max_iterations=sub.max_turns if sub.max_turns is not None else parent.max_iterations,
                skill_dirs=[],   # skill 清单已由 _system_for 拼入，禁用再探测
                subagent_dirs=[],  # 禁用子代理再探测，防 task 重入（防递归）
            )
            return child.run(prompt) or "(no summary)"
        except Exception as exc:  # 子代理异常 → 描述性字符串，不破父循环
            return f"Subagent '{agent_type}' failed: {exc}"

    return Tool(func=task, name="task")
