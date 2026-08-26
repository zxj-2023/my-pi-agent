"""MCP 客户端（产品层）—— 原生异步 Stdio 子进程连接与 extension 入口。"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import mcp.types as mcp_types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from my_agent_core.tools import Tool, ToolResult

if TYPE_CHECKING:
    from my_agent_core.extensions import ExtensionAPI


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str]
    env: dict[str, str] | None = None


class MCPConnection:
    """单个 MCP Server 的原生异步连接管理器。"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._session: ClientSession | None = None
        self._exit_stack = contextlib.AsyncExitStack()

    async def start(self) -> None:
        """在当前事件循环中异步建立 Stdio 子进程长连接并完成初始化握手。"""
        server_env = os.environ.copy()
        if self.config.env:
            server_env.update(self.config.env)

        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=server_env,
        )

        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        self._session = session
        await session.initialize()

    async def list_tools(self) -> list[mcp_types.Tool]:
        """异步拉取远程工具列表。"""
        if self._session is None:
            raise RuntimeError(f"MCP server '{self.config.name}' is not connected")
        res = await self._session.list_tools()
        return res.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """异步调用远程工具。"""
        if self._session is None:
            return ToolResult(
                ok=False,
                error=f"MCP server '{self.config.name}' is not connected",
                meta={"server": self.config.name},
            )

        try:
            call_res = await self._session.call_tool(name=name, arguments=arguments)
        except Exception as exc:
            return ToolResult(
                ok=False,
                error=f"MCP tool '{name}' failed: {exc}",
                meta={"server": self.config.name},
            )

        # 拼接文本输出
        texts = []
        for content in call_res.content:
            if hasattr(content, "text"):
                texts.append(content.text)
            else:
                texts.append(str(content))
        out_text = "\n".join(texts) or "(no output)"

        is_err = getattr(call_res, "is_error", getattr(call_res, "isError", False))
        if is_err:
            return ToolResult(
                ok=False,
                error=out_text,
                meta={"server": self.config.name, "is_error": True},
            )
        return ToolResult(ok=True, data=out_text, meta={"server": self.config.name})

    async def close(self) -> None:
        """优雅关闭。"""
        await self._exit_stack.aclose()
        self._session = None


class MCPClientManager:
    """多 MCP Server 管理器。"""

    def __init__(self):
        self.connections: dict[str, MCPConnection] = {}

    def load_config(self, path: Path | str) -> list[MCPServerConfig]:
        """读取 .mcp.json。"""
        p = Path(path)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Invalid JSON in {p}: {exc}") from exc

        servers = data.get("mcpServers", {})
        configs = []
        for name, srv in servers.items():
            configs.append(
                MCPServerConfig(
                    name=name,
                    command=srv.get("command", ""),
                    args=srv.get("args", []),
                    env=srv.get("env"),
                )
            )
        return configs

    async def connect_server(self, config: MCPServerConfig) -> list[Tool]:
        """异步连接单个 Server 并返回包装后的 Tool 列表。"""
        conn = MCPConnection(config)
        await conn.start()
        self.connections[config.name] = conn

        mcp_tools = await conn.list_tools()
        wrapped_tools = []
        for t in mcp_tools:
            tool_name = t.name
            schema = getattr(t, "input_schema", getattr(t, "inputSchema", {}))

            def _make_handler(target_conn: MCPConnection, target_name: str):
                async def _handler(args: dict[str, Any]) -> ToolResult:
                    return await target_conn.call_tool(target_name, args)

                return _handler

            wrapped = Tool(
                func=_make_handler(conn, tool_name),
                name=tool_name,
                description=t.description or "",
                raw_schema=schema,
                timeout=120.0,
                is_parallel_safe=True,
            )
            wrapped_tools.append(wrapped)
        return wrapped_tools

    async def close_all(self) -> None:
        """异步关闭所有连接。"""
        for conn in self.connections.values():
            with contextlib.suppress(Exception):
                await conn.close()
        self.connections.clear()


# ── 标准 Extension 入口协议 ──────────────────────────────────────────


async def extension(api: ExtensionAPI) -> None:
    """MCP Extension 标准入口函数。"""
    config_path = Path.cwd() / ".mcp.json"
    if not config_path.exists():
        return

    manager = MCPClientManager()
    try:
        server_configs = manager.load_config(config_path)
    except Exception as exc:
        print(f"[MCP] 解析 .mcp.json 失败: {exc}")
        return

    registered_tools: list[str] = []
    for cfg in server_configs:
        try:
            tools = await manager.connect_server(cfg)
            for t in tools:
                api.register_tool(t)
                registered_tools.append(t.name)
        except Exception as exc:
            print(f"[MCP] 连接服务 '{cfg.name}' 失败: {exc}")

    @api.command("mcp", description="查看当前已连接的 MCP 服务状态与工具列表")
    def cmd_mcp(args: str | None = None) -> str:
        if not manager.connections:
            return "当前未连接任何 MCP 服务。"
        lines = ["=== MCP 服务状态 ==="]
        for name, conn in manager.connections.items():
            status = "Connected" if conn._session is not None else "Disconnected"
            lines.append(f"- {name}: {status} (命令: {conn.config.command})")
        lines.append(f"已加载工具: {', '.join(registered_tools) or '(none)'}")
        return "\n".join(lines)
