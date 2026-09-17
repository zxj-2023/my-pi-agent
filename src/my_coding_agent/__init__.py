"""my_coding_agent 公共 API（产品层：文件工具 + MCP + 业务装配）。"""

from typing import TYPE_CHECKING

from my_coding_agent.agent import CodingAgent
from my_coding_agent.file_reference import FileReferenceParser
from my_coding_agent.macro import MacroEngine
from my_coding_agent.mcp import MCPClientManager, MCPConnection, MCPServerConfig
from my_coding_agent.mutation_queue import FileMutationQueue
from my_coding_agent.paths import AgentPaths
from my_coding_agent.permissions import PermissionGate, PermissionMode, PermissionRequest
from my_coding_agent.prompt import build_default_coding_prompt
from my_coding_agent.settings import CompactionSettings, Settings, load_settings, save_settings
from my_coding_agent.tools import (
    EditBlock,
    build_coding_tools,
    make_bash_tool,
    make_edit_tool,
    make_find_tool,
    make_grep_tool,
    make_ls_tool,
    make_read_tool,
    make_write_tool,
    resolve_path,
)

__all__ = [
    "AgentPaths",
    "CodingAgent",
    "CompactionSettings",
    "FileReferenceParser",
    "MacroEngine",
    "Settings",
    "load_settings",
    "save_settings",
    "build_coding_tools",
    "build_default_coding_prompt",
    "FileMutationQueue",
    "resolve_path",
    "RpcServer",
    "EditBlock",
    "make_read_tool",
    "make_write_tool",
    "make_edit_tool",
    "make_bash_tool",
    "make_grep_tool",
    "make_find_tool",
    "make_ls_tool",
    "MCPServerConfig",
    "MCPConnection",
    "MCPClientManager",
    "PermissionGate",
    "PermissionRequest",
    "PermissionMode",
]

if TYPE_CHECKING:
    from my_coding_agent.rpc_server import RpcServer


def __getattr__(name: str):
    if name == "RpcServer":
        from my_coding_agent.rpc_server import RpcServer

        return RpcServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
