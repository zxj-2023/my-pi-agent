"""内置扩展包 —— 提供开箱即用的框架级扩展（如 MCP 客户端）。"""

from .mcp import (
    MCPClientManager,
    MCPConnection,
    MCPServerConfig,
)
from .mcp import (
    extension as mcp_extension,
)

__all__ = [
    "MCPClientManager",
    "MCPConnection",
    "MCPServerConfig",
    "mcp_extension",
]
