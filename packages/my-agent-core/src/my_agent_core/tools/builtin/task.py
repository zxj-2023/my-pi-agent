"""内置工具：task（subagent 委派）工厂。"""

from my_agent_core.subagents import SubagentManager
from my_agent_core.tasks import TaskManager, TaskStatus
from my_agent_core.tools import Tool

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_agent_core.agent import Agent


def make_task_tool(manager: SubagentManager, parent: "Agent") -> Tool:
    """产出内置 `task` 委派工具（工具桥：调 TaskManager.start_task → 转字符串）。"""
    task_manager = TaskManager(manager, parent)

    def task(prompt: str, agent_type: str = "default") -> str:
        """Spawn a subagent with fresh context to complete the given prompt.
        agent_type: name of the subagent definition (see available agents)."""
        t = task_manager.start_task(prompt, agent_type)
        return (
            t.result
            if t.status is TaskStatus.COMPLETED
            else (t.error or "(no summary)")
        )

    return Tool(func=task, name="task")
