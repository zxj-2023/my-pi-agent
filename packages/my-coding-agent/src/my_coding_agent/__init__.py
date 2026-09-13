"""my_coding_agent 公共 API（产品层：文件工具 + MCP + 业务装配）。"""

from my_coding_agent.agent import CodingAgent
from my_coding_agent.file_reference import FileReferenceParser
from my_coding_agent.mcp import MCPClientManager, MCPConnection, MCPServerConfig
from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.permissions import PermissionGate, PermissionMode, PermissionRequest
from my_coding_agent.prompt import build_default_coding_prompt
from my_coding_agent.tools import (
    EditBlock,
    build_coding_tools,
    make_bash_tool,
    make_edit_tool,
    make_find_tool,
    make_grep_tool,
    make_read_tool,
    make_write_tool,
    resolve_path,
)

__all__ = [
    "CodingAgent",
    "FileReferenceParser",
    "build_coding_tools",
    "build_default_coding_prompt",
    "FileMutationQueue",
    "resolve_path",
    "EditBlock",
    "make_read_tool",
    "make_write_tool",
    "make_edit_tool",
    "make_bash_tool",
    "make_grep_tool",
    "make_find_tool",
    "MCPServerConfig",
    "MCPConnection",
    "MCPClientManager",
    "PermissionGate",
    "PermissionRequest",
    "PermissionMode",
]
