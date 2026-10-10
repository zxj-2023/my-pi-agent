"""工具声明与分发 —— 上行翻译层。"""

from .core import (
    DEFAULT_TOOL_MAX_BYTES,
    DEFAULT_TOOL_MAX_LINES,
    Tool,
    ToolResult,
    tool,
    truncate_tool_output,
)
from .prompt import format_cwd_section, format_rules_section, format_tools_section

__all__ = [
    "DEFAULT_TOOL_MAX_BYTES",
    "DEFAULT_TOOL_MAX_LINES",
    "Tool",
    "ToolResult",
    "tool",
    "truncate_tool_output",
    "format_cwd_section",
    "format_rules_section",
    "format_tools_section",
]
