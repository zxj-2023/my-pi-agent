"""MCP 客户端（产品层）—— 原生异步 Stdio 子进程连接与 extension 入口。"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import mcp.types as mcp_types  # pyright: ignore[reportMissingImports]
from mcp.client.session import ClientSession  # pyright: ignore[reportMissingImports]
from mcp.client.stdio import (  # pyright: ignore[reportMissingImports]
    StdioServerParameters,
    stdio_client,
)
from my_agent_core.tools import (  # pyright: ignore[reportMissingImports]
    Tool,
    ToolResult,
)

if TYPE_CHECKING:
    from my_agent_core.extensions import (  # pyright: ignore[reportMissingImports]
        ExtensionAPI,
    )


@dataclass
class MCPServerConfig:
    """单个 MCP Server 的连接配置。

    ``transport`` 决定使用哪条链路：
    - ``stdio``（默认）：拉起 ``command`` 子进程；
    - ``http``：Streamable HTTP，连接 ``url``；
    - ``sse``：旧版 SSE，连接 ``url``。
    """

    name: str
    command: str = ""
    args: list[str] | None = None
    env: dict[str, str] | None = None
    transport: str = "stdio"
    url: str = ""
    headers: dict[str, str] | None = None


def parse_server_entry(name: str, entry: dict[str, Any]) -> MCPServerConfig | None:
    """把一条 MCP server 配置解析为 ``MCPServerConfig``。

    兼容两种写法：
    - ``{"command": "npx", "args": [...], "env": {...}}`` → stdio
    - ``{"type": "http"|"sse", "url": "...", "headers": {...}}`` → 远端传输
    - ``{"url": "..."}`` 无 type 时按 http 处理

    无法识别的条目返回 ``None``（由调用方跳过）。
    """
    if not isinstance(entry, dict):
        return None

    explicit_type = str(entry.get("type") or "").strip().lower()
    url = str(entry.get("url") or "").strip()
    command = str(entry.get("command") or "").strip()

    # 显式声明远端传输，或只给了 url
    if explicit_type in ("http", "streamable-http", "streamablehttp", "sse") or (url and not command):
        if not url:
            return None
        transport = "sse" if explicit_type == "sse" else "http"
        headers = entry.get("headers")
        return MCPServerConfig(
            name=name,
            transport=transport,
            url=url,
            headers=dict(headers) if isinstance(headers, dict) else None,
        )

    # 默认 stdio
    if not command:
        return None
    return MCPServerConfig(
        name=name,
        command=command,
        args=list(entry.get("args") or []),
        env=entry.get("env"),
    )


class MCPConnection:
    """单个 MCP Server 的原生异步连接管理器（支持 stdio / http / sse 三种传输）。"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._session: ClientSession | None = None
        self._exit_stack = contextlib.AsyncExitStack()

    async def start(self) -> None:
        """在当前事件循环中异步建立长连接并完成初始化握手。"""
        if self.config.transport == "stdio":
            streams = await self._open_stdio()
        elif self.config.transport == "http":
            streams = await self._open_http()
        elif self.config.transport == "sse":
            streams = await self._open_sse()
        else:
            raise ValueError(f"Unsupported MCP transport: {self.config.transport}")

        read_stream, write_stream = streams
        session = await self._exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        self._session = session
        await session.initialize()

    async def _open_stdio(self):
        """stdio 传输：拉起子进程。"""
        server_env = os.environ.copy()
        if self.config.env:
            server_env.update(self.config.env)

        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args or [],
            env=server_env,
        )
        return await self._exit_stack.enter_async_context(stdio_client(params))

    async def _open_http(self):
        """Streamable HTTP 传输：直连远端 URL，headers 透传（如 Authorization）。"""
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        http_client = create_mcp_http_client(headers=self.config.headers or None)
        await self._exit_stack.enter_async_context(http_client)
        return await self._exit_stack.enter_async_context(
            streamable_http_client(self.config.url, http_client=http_client)
        )

    async def _open_sse(self):
        """SSE 传输（旧版）：直连远端 URL。"""
        from mcp.client.sse import sse_client

        return await self._exit_stack.enter_async_context(
            sse_client(self.config.url, headers=self.config.headers or None)
        )

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
            text_val = getattr(content, "text", None)
            if text_val is not None:
                texts.append(str(text_val))
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
        self._tools: list[Tool] = []
        self._configs: list[MCPServerConfig] = []

    @classmethod
    def from_config_file(cls, path: Path | str) -> MCPClientManager:
        """从配置文件构造 MCPClientManager 实例。"""
        mgr = cls()
        mgr._configs = mgr.load_config(path)
        return mgr

    @staticmethod
    def load_config_file(path: Path | str) -> list[MCPServerConfig]:
        """纯函数式读取 ``.mcp.json``，不构造管理器实例。"""
        return MCPClientManager().load_config(path)

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
            cfg = parse_server_entry(name, srv)
            if cfg is not None:
                configs.append(cfg)
        self._configs = configs
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
            setattr(wrapped, "is_mcp", True)
            wrapped_tools.append(wrapped)
        self._tools.extend(wrapped_tools)
        return wrapped_tools

    async def connect_all(self, configs: list[MCPServerConfig] | None = None) -> list[Tool]:
        """连接所有配置的服务并返回收集的所有工具。"""
        target_configs = configs if configs is not None else self._configs
        tools: list[Tool] = []
        for cfg in target_configs:
            server_tools = await self.connect_server(cfg)
            tools.extend(server_tools)
        return tools

    def get_all_tools(self) -> list[Tool]:
        """获取当前所有已连接的工具列表。"""
        return list(self._tools)

    async def close_all(self) -> None:
        """异步关闭所有连接。"""
        for conn in self.connections.values():
            with contextlib.suppress(Exception):
                await conn.close()
        self.connections.clear()
        self._tools.clear()


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
