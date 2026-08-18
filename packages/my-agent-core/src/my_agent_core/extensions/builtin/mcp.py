"""MCP 客户端内置扩展 —— Stdio 子进程连接、同步/异步线程桥接与 extension 入口。"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import json
import os
import threading
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
    """单个 MCP Server 的连接生命周期管理器（后台事件循环线程）。"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._started = threading.Event()
        self._stopped = threading.Event()
        self._init_error: Exception | None = None

    def start(self, timeout: float = 30.0) -> None:
        """在后台守护线程中启动事件循环并完成初始化。"""
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name=f"MCP-{self.config.name}"
        )
        self._thread.start()
        if not self._started.wait(timeout):
            self.close()
            raise TimeoutError(
                f"MCP server '{self.config.name}' failed to start within {timeout}s"
            )
        if self._init_error is not None:
            self.close()
            raise RuntimeError(
                f"MCP server '{self.config.name}' failed to initialize: {self._init_error}"
            )

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_main())
        except Exception as exc:
            self._init_error = exc
            self._started.set()
        finally:
            loop.close()

    async def _async_main(self) -> None:
        server_env = os.environ.copy()
        if self.config.env:
            server_env.update(self.config.env)

        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=server_env,
        )

        async with (
            stdio_client(params) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            self._session = session
            await session.initialize()
            self._started.set()
            # 阻塞直到显式通知关闭
            while not self._stopped.is_set():
                await asyncio.sleep(0.1)

    def list_tools(self, timeout: float = 30.0) -> list[mcp_types.Tool]:
        """拉取远程工具列表。"""
        if self._loop is None or self._session is None:
            raise RuntimeError(f"MCP server '{self.config.name}' is not connected")
        future = asyncio.run_coroutine_threadsafe(
            self._session.list_tools(), self._loop
        )
        res = future.result(timeout=timeout)
        return res.tools

    def call_tool(
        self, name: str, arguments: dict[str, Any], timeout: float = 120.0
    ) -> ToolResult:
        """调用远程工具。"""
        if self._loop is None or self._session is None:
            return ToolResult(
                ok=False,
                error=f"MCP server '{self.config.name}' is not connected",
                meta={"server": self.config.name},
            )

        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name=name, arguments=arguments),
            self._loop,
        )
        try:
            call_res = future.result(timeout=timeout)
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

    def close(self) -> None:
        """优雅关闭。"""
        self._stopped.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


class MCPClientManager:
    """多 MCP Server 管理器。"""

    def __init__(self):
        self.connections: dict[str, MCPConnection] = {}
        atexit.register(self.close_all)

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

    def connect_server(self, config: MCPServerConfig) -> list[Tool]:
        """连接单个 Server 并返回包装后的 Tool 列表。"""
        conn = MCPConnection(config)
        conn.start()
        self.connections[config.name] = conn

        mcp_tools = conn.list_tools()
        wrapped_tools = []
        for t in mcp_tools:
            tool_name = t.name
            schema = getattr(t, "input_schema", getattr(t, "inputSchema", {}))

            def _make_handler(target_conn: MCPConnection, target_name: str):
                return lambda args: target_conn.call_tool(target_name, args)

            wrapped = Tool(
                func=_make_handler(conn, tool_name),
                name=tool_name,
                description=t.description or "",
                raw_schema=schema,
                timeout=120.0,
            )
            wrapped_tools.append(wrapped)
        return wrapped_tools

    def close_all(self) -> None:
        """关闭所有连接。"""
        for conn in self.connections.values():
            with contextlib.suppress(Exception):
                conn.close()
        self.connections.clear()


# ── 标准 Extension 入口协议 ──────────────────────────────────────────

def extension(api: ExtensionAPI) -> None:
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
            tools = manager.connect_server(cfg)
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
            status = "Connected" if conn._started.is_set() else "Disconnected"
            lines.append(f"- {name}: {status} (命令: {conn.config.command})")
        lines.append(f"已加载工具: {', '.join(registered_tools) or '(none)'}")
        return "\n".join(lines)
