"""生产级编码智能体门面 (Dual API 架构与 6 大工具自动装配)。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from my_agent_core import Agent  # pyright: ignore[reportMissingImports]
from my_agent_core.events import Event  # pyright: ignore[reportMissingImports]
from my_agent_core.session import Session  # pyright: ignore[reportMissingImports]
from my_agent_core.tools import Tool  # pyright: ignore[reportMissingImports]

from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.prompt import build_default_coding_prompt
from my_coding_agent.tools import build_coding_tools


class CodingAgent:
    """生产级编码智能体门面 (Dual API 架构)"""

    def __init__(
        self,
        *,
        workspace: str | Path,
        llm,
        session: Session,
        system_prompt: str | None = None,
        extra_tools: list[Tool] | tuple[Tool, ...] = (),
        **kw,
    ):
        self.workspace = Path(workspace).resolve()
        self.mutation_queue = FileMutationQueue()

        if isinstance(session, (str, Path)):
            session = Session(path=Path(session))

        # 1. 自动生成或应用系统提示词
        effective_prompt = system_prompt if system_prompt is not None else build_default_coding_prompt(self.workspace)

        # 2. 构造框架通用 Agent
        self.agent = Agent(
            llm=llm,
            session=session,
            tools=list(extra_tools),
            system_prompt=effective_prompt,
            **kw,
        )

        # 3. 装配 6 大编码专属工具
        coding_tools = build_coding_tools(
            self.workspace,
            mutation_queue=self.mutation_queue,
            background_runner=self.agent.background_runner,
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

    @property
    def session(self) -> Session:
        """底层会话对象。"""
        return self.agent.session

    async def compact(self):
        """手动触发智能上下文压缩。"""
        return await self.agent.compact()

    async def run(self, user_input: str) -> str:
        """批处理高阶入口：聚合最终助手文本"""
        res = await self.agent.run(user_input)
        return res if res is not None else ""

    async def run_stream(self, user_input: str) -> AsyncIterator[Event]:
        """流式一等公民入口：实时产出全生命周期事件"""
        async for event in self.agent.prompt_stream(user_input):
            yield event
