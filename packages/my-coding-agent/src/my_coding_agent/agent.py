"""产品层薄装配：文件工具工厂 + CodingAgent（框架 Agent + 文件工具自动装配）。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from my_agent_core import Agent  # pyright: ignore[reportMissingImports]
from my_agent_core.tools import Tool  # pyright: ignore[reportMissingImports]

if TYPE_CHECKING:
    from my_agent_core.background import (  # pyright: ignore[reportMissingImports]
        BackgroundRunner,
    )

from my_coding_agent.tools import (
    make_bash_tool,
    make_edit_tool,
    make_read_tool,
    make_write_tool,
)


def build_coding_tools(
    workspace: str | Path, background_runner: BackgroundRunner | None = None
) -> list[Tool]:
    """返回 4 个文件工具（read/write/edit/bash），各绑定 workspace（路径逃逸防护）。"""
    workspace = Path(workspace).resolve()
    return [
        make_read_tool(workspace),
        make_write_tool(workspace),
        make_edit_tool(workspace),
        make_bash_tool(workspace, background_runner=background_runner),
    ]


class CodingAgent:
    """产品层：框架 Agent + 文件工具自动装配（薄封装）。"""

    def __init__(
        self,
        *,
        workspace: str | Path,
        llm,
        session,
        system_prompt: str | None = None,
        extra_tools: list | tuple = (),
        **kw,
    ):
        self.agent = Agent(
            llm=llm,
            tools=list(extra_tools),
            session=session,
            system_prompt=system_prompt,
            **kw,
        )
        coding_tools = build_coding_tools(
            workspace, background_runner=self.agent.background_runner
        )
        for t in coding_tools:
            self.agent.registry.register(t)

    @property
    def task_store(self):
        """底层的任务看板仓库。"""
        return self.agent.task_store

    @property
    def background_runner(self):
        """底层的后台作业执行器。"""
        return self.agent.background_runner

    async def run(self, user_input: str):
        return await self.agent.run(user_input)
