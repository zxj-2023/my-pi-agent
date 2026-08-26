"""my_coding_agent 公共 API（产品层：文件工具 + MCP + 薄装配）。"""

from my_coding_agent.agent import CodingAgent, build_coding_tools
from my_coding_agent.mcp import MCPClientManager, MCPConnection, MCPServerConfig

__all__ = [
    "CodingAgent",
    "build_coding_tools",
    "MCPServerConfig",
    "MCPConnection",
    "MCPClientManager",
]