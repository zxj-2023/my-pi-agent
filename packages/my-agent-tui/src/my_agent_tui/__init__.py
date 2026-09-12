"""my_agent_tui: Terminal UI and interactive REPL layer."""

from my_agent_tui.cli import build_prompt_session, main, run_cli_loop
from my_agent_tui.cli_base import _force_utf8_streams, _is_utf8_encoding
from my_agent_tui.commands import CommandContext, CommandDispatcher
from my_agent_tui.renderer import EventRenderer, TextChunk

__version__ = "0.1.0"

__all__ = [
    "CommandContext",
    "CommandDispatcher",
    "EventRenderer",
    "TextChunk",
    "main",
    "run_cli_loop",
    "build_prompt_session",
    "_force_utf8_streams",
    "_is_utf8_encoding",
]
