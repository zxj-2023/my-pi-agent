"""subagent 委派的任务生命周期：Task 模型 + TaskStatus + TaskManager（对标 OpenHands task/manager.py）。

委派逻辑（_filter_tools/_system_for）从 subagents.py 移入；make_task_tool 已迁至
tools/builtin.py（工具桥，真实逻辑在 TaskManager）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from my_agent_core.session import Session
from my_agent_core.subagents import DEFAULT_SUBAGENT, Subagent, SubagentManager

if TYPE_CHECKING:
    from my_agent_core.agent import Agent


class TaskStatus(StrEnum):
    """委派任务三态。"""

    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Task:
    """一次委派任务：有 id/状态/结果，可查询（不再是一次性返回值）。"""

    id: str
    status: TaskStatus
    result: str | None = None
    error: str | None = None

    def set_result(self, result: str) -> None:
        """标记成功。"""
        self.result = result
        self.error = None
        self.status = TaskStatus.COMPLETED

    def set_error(self, error: str) -> None:
        """标记失败。"""
        self.error = error
        self.result = None
        self.status = TaskStatus.ERROR


def _system_for(sub: Subagent, parent: Agent) -> str:
    """子代理 system = 正文 + （若有 skills）子集清单；不收父 system prompt（Claude 官方语义）。"""
    parts = [sub.content]
    if sub.skills:
        block = parent.skill_manager.format_prompt(sub.skills)
        if block:
            parts.append(block)
    return "\n\n".join(p for p in parts if p)


def _filter_tools(parent: Agent, sub: Subagent) -> list:
    """父工具集按白/黑名单过滤；task 与 memory 永不出现（防递归与隔离）。"""
    tools = [t for t in parent.registry.list() if t.name not in ("task", "memory")]
    if sub.tools is not None:
        allowed = set(sub.tools)
        tools = [t for t in tools if t.name in allowed]
    black = set(sub.disallowed_tools)
    tools = [t for t in tools if t.name not in black]
    return tools


class TaskManager:
    """委派任务的生命周期管理器（对标 OpenHands TaskManager）。"""

    def __init__(self, manager: SubagentManager, parent: Agent):
        self._manager = manager  # 查 agent 定义
        self._parent = parent  # 供 llm/工具集/skill_manager/max_iterations
        self._counter = 0
        self._active_agents: dict[str, Agent] = {}  # 追踪运行中的子代理实例 (task_id -> Agent)

    def steer_task(self, task_id: str, message: str) -> bool:
        """向指定运行中的子代理发送 Steer 转向指令。"""
        agent = self._active_agents.get(task_id)
        if agent is not None:
            agent.steer(message)
            return True
        return False

    def follow_up_task(self, task_id: str, message: str) -> bool:
        """向指定运行中的子代理发送 Follow-up 追问指令。"""
        agent = self._active_agents.get(task_id)
        if agent is not None:
            agent.follow_up(message)
            return True
        return False

    async def start_task(self, prompt: str, subagent_type: str = "default") -> Task:
        """异步：建 Task(RUNNING) → spawn → run → 更新状态 → 返回。"""
        task = self._create_task(subagent_type)
        try:
            task.set_result(await self._run(prompt, subagent_type, task.id))
        except Exception as exc:
            task.set_error(str(exc))
        return task

    def _create_task(self, subagent_type: str) -> Task:
        self._counter += 1
        return Task(id=f"task_{self._counter:08x}", status=TaskStatus.RUNNING)

    async def _run(self, prompt: str, subagent_type: str, task_id: str) -> str:
        """查定义 → 建独立 session → 过滤工具 → spawn 子 Agent → run → 返回最终文本。"""
        from my_agent_core.agent import Agent  # 延迟 import 避循环

        sub = self._manager.get(subagent_type)
        if sub is None and subagent_type == "default":
            sub = DEFAULT_SUBAGENT
        if sub is None:
            available = ", ".join(sorted(self._manager.subagents)) or "(none)"
            raise ValueError(
                f"Unknown subagent '{subagent_type}'. Available: {available}"
            )
        child_session = Session(
            path=self._parent.session.path.parent
            / "subagents"
            / f"agent-{task_id}.jsonl",
            cwd=self._parent.session.cwd,
            metadata={
                "agent_type": subagent_type,
                "parent_session_id": self._parent.session.id,
            },
        )
        child_session.save()
        child = Agent(
            llm=self._parent.llm,
            tools=_filter_tools(self._parent, sub),
            session=child_session,
            system_prompt=_system_for(sub, self._parent),
            model=sub.model,
            max_iterations=sub.max_turns
            if sub.max_turns is not None
            else self._parent.max_iterations,
            skill_dirs=[],  # skill 清单已由 _system_for 拼入
            subagent_dirs=[],  # 防递归：禁用子代理再探测
            memory_dir=False,  # 隔离：子代理禁用长期记忆探测与维护
            plugin_dirs=[],  # 隔离：子代理禁用插件再探测（防递归注册 task 工具）
        )
        self._active_agents[task_id] = child
        try:
            return (await child.run(prompt)) or "(no summary)"
        except Exception as exc:
            raise RuntimeError(f"Subagent '{subagent_type}' failed: {exc}") from exc
        finally:
            self._active_agents.pop(task_id, None)
