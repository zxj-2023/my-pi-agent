"""生产级编码智能体门面 (Dual API 架构与 6 大工具自动装配)。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from my_agent_core import Agent  # pyright: ignore[reportMissingImports]
from my_agent_core.events import Event  # pyright: ignore[reportMissingImports]
from my_agent_core.hooks import ToolCallHook  # pyright: ignore[reportMissingImports]
from my_agent_core.session import Session  # pyright: ignore[reportMissingImports]
from my_agent_core.tools import Tool  # pyright: ignore[reportMissingImports]

from my_coding_agent.mcp import MCPClientManager
from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.prompt import build_default_coding_prompt
from my_coding_agent.tools import build_coding_tools

if TYPE_CHECKING:
    from my_coding_agent.permissions import PermissionGate

logger = logging.getLogger(__name__)


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
        permission_gate: PermissionGate | None = None,
        auto_load_mcp: bool = True,
        **kw,
    ):
        self.workspace = Path(workspace).resolve()
        self.mutation_queue = FileMutationQueue()
        self._permission_gate = permission_gate
        self.auto_load_mcp = auto_load_mcp
        self._mcp_manager: MCPClientManager | None = None
        self._mcp_loaded: bool = False

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

        # 3. 若注入了权限门禁，注册到 ToolCallHook
        if self._permission_gate is not None:
            self.agent.hooks.register(ToolCallHook, self._permission_gate)

        # 4. 装配 6 大编码专属工具
        coding_tools = build_coding_tools(
            self.workspace,
            mutation_queue=self.mutation_queue,
            background_runner=self.agent.background_runner,
        )
        for t in coding_tools:
            self.agent.registry.register(t)

    @property
    def permission_gate(self) -> PermissionGate | None:
        """底层安全权限门禁。"""
        return self._permission_gate

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

    @property
    def mcp_manager(self) -> MCPClientManager | None:
        """底层 MCP 客户端管理器。"""
        return self._mcp_manager

    async def ensure_mcp_loaded(self) -> None:
        """按需自动扫描并加载工作区 .mcp.json 配置的 MCP 服务与工具。"""
        if not self.auto_load_mcp or self._mcp_loaded:
            return
        self._mcp_loaded = True

        mcp_file = self.workspace / ".mcp.json"
        if not mcp_file.is_file():
            return

        try:
            if self._mcp_manager is None:
                self._mcp_manager = MCPClientManager.from_config_file(mcp_file)
            await self._mcp_manager.connect_all()
            tools = self._mcp_manager.get_all_tools()
            for t in tools:
                setattr(t, "is_mcp", True)
                self.agent.registry.register(t)
        except Exception as exc:
            logger.warning("加载工作区 .mcp.json 失败: %s", exc)

    async def close_mcp(self) -> None:
        """异步关闭并回收已挂载的 MCP 连接与子进程资源。"""
        if self._mcp_manager is not None:
            await self._mcp_manager.close_all()
            self._mcp_manager = None
        self._mcp_loaded = False

    async def __aenter__(self) -> CodingAgent:
        """异步上下文管理器入口：自动确保 MCP 工具完成挂载。"""
        await self.ensure_mcp_loaded()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """异步上下文管理器出口：优雅回收 MCP 资源。"""
        await self.close_mcp()

    async def compact(self):
        """手动触发智能上下文压缩。"""
        return await self.agent.compact()

    async def run(self, user_input: str) -> str:
        """批处理高阶入口：聚合最终助手文本"""
        await self.ensure_mcp_loaded()
        res = await self.agent.run(user_input)
        return res if res is not None else ""

    async def run_stream(self, user_input: str) -> AsyncIterator[Event]:
        """流式一等公民入口：实时产出全生命周期事件"""
        await self.ensure_mcp_loaded()
        async for event in self.agent.prompt_stream(user_input):
            yield event
