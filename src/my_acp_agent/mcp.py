"""ACP ``mcpServers`` → ``MCPServerConfig`` 的翻译层。

ACP 的 ``session/new`` / ``session/load`` 会携带客户端注入的 MCP server 列表，
本模块把它们转成 ``my_coding_agent.mcp.MCPServerConfig``，交给既有的
``MCPClientManager`` 连接。

支持三种 ACP 传输：

| ACP 类型 | 字段 | 映射到 |
| :--- | :--- | :--- |
| ``McpServerStdio`` | ``command`` / ``args`` / ``env`` | stdio 子进程 |
| ``HttpMcpServer`` | ``url`` / ``headers`` | Streamable HTTP |
| ``SseMcpServer`` | ``url`` / ``headers`` | 旧版 SSE |

``AcpMcpServer``（``type: "acp"``）表示由 Agent 自身托管的 MCP 连接，
不是外部 server，直接跳过。
"""

from __future__ import annotations

import logging
from typing import Any

from my_coding_agent.mcp import MCPServerConfig

logger = logging.getLogger(__name__)

__all__ = ["to_mcp_server_config", "to_mcp_server_configs"]


def _field(obj: Any, key: str) -> Any:
    """同时支持 pydantic 模型与裸 dict 的字段读取。"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _name_value_pairs_to_dict(items: Any) -> dict[str, str] | None:
    """把 ``[{name, value}]`` 列表（或已是 dict）转成普通 dict。"""
    if not items:
        return None
    if isinstance(items, dict):
        return {str(k): str(v) for k, v in items.items()} or None
    out: dict[str, str] = {}
    for item in items:
        name = _field(item, "name")
        value = _field(item, "value")
        if name:
            out[str(name)] = str(value if value is not None else "")
    return out or None


def _env_to_dict(env: Any) -> dict[str, str] | None:
    """ACP 的 env 是 ``[{name, value}]`` 列表，转成普通 dict。"""
    return _name_value_pairs_to_dict(env)


def _headers_to_dict(headers: Any) -> dict[str, str] | None:
    """ACP 的 headers 是 ``[{name, value}]`` 列表，转成普通 dict。"""
    return _name_value_pairs_to_dict(headers)


def _field(obj: Any, key: str) -> Any:
    """同时支持 pydantic 模型与裸 dict 的字段读取。"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def to_mcp_server_config(server: Any) -> MCPServerConfig | None:
    """把单个 ACP MCP server 描述转成 ``MCPServerConfig``。

    同时接受 ACP schema 模型与裸 dict（便于手写配置与测试）。
    无法识别或缺少必要字段时返回 ``None``。
    """
    name = _field(server, "name") or "unnamed"
    server_type = str(_field(server, "type") or "").strip().lower()

    # stdio：有 command 字段
    command = _field(server, "command")
    if command:
        return MCPServerConfig(
            name=str(name),
            transport="stdio",
            command=str(command),
            args=[str(a) for a in (_field(server, "args") or [])],
            env=_env_to_dict(_field(server, "env")),
        )

    # http / sse：有 url 字段
    url = _field(server, "url")
    if url:
        transport = "sse" if server_type == "sse" else "http"
        return MCPServerConfig(
            name=str(name),
            transport=transport,
            url=str(url),
            headers=_headers_to_dict(_field(server, "headers")),
        )

    # AcpMcpServer（type == "acp"）：由 Agent 自身托管，非外部 server
    if server_type == "acp":
        logger.debug("跳过 ACP 自托管 MCP server: %s", name)
        return None

    logger.warning("无法识别的 MCP server 描述，已跳过: name=%s type=%s", name, server_type)
    return None


def to_mcp_server_configs(servers: Any) -> list[MCPServerConfig]:
    """批量翻译，静默丢弃无法识别的条目。"""
    if not servers:
        return []
    out: list[MCPServerConfig] = []
    for server in servers:
        cfg = to_mcp_server_config(server)
        if cfg is not None:
            out.append(cfg)
    return out
