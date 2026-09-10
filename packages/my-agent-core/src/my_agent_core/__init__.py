"""my_agent_core 公共 API。"""

from my_agent_core.agent import Agent
from my_agent_core.background import (  # pyright: ignore[reportMissingImports]
    BackgroundJob,
    BackgroundRunner,
)
from my_agent_core.context import ContextManager
from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    AgentStartDecision,
    BeforeModelCall,
    BeforeModelCallDecision,
    ContextCompacted,
    DecisionRegistry,
    Event,
    HookRegistry,
    HookResult,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolCallDecision,
    ToolExecutionEnd,
    ToolExecutionStart,
    ToolExecutionUpdate,
    ToolResultDecision,
    ToolsChanged,
    TurnEnd,
    TurnStart,
    UserInput,
    UserInputDecision,
)
from my_agent_core.extensions import ExtensionAPI, ExtensionManager
from my_agent_core.loop import (
    AgentEvent,
    CancellationToken,
    _provider_context,
    run_agent_loop,
)
from my_agent_core.memory import MemoryStore, make_memory_tool
from my_agent_core.message_queue import MessageQueue, MessageType, QueuedMessage
from my_agent_core.plugins import (
    Plugin,
    PluginAuthor,
    PluginManager,
    PluginManifest,
)
from my_agent_core.registry import ToolRegistry
from my_agent_core.session import Session, SessionStore, SessionTree
from my_agent_core.subagent_tasks import (  # pyright: ignore[reportMissingImports]
    SubagentTask,
    SubagentTaskManager,
    SubagentTaskStatus,
)
from my_agent_core.task_store import (  # pyright: ignore[reportMissingImports]
    TaskItem,
    TaskStore,
)
from my_agent_core.tool_history import (  # pyright: ignore[reportMissingImports]
    ToolHistoryRepair,
    repair_tool_history,
)
from my_agent_core.tools import Tool, ToolResult, tool
from my_agent_core.tools.builtin.task_tools import (  # pyright: ignore[reportMissingImports]
    make_task_tools,
    make_todo_tool,
)

__all__ = [
    "Agent",
    "tool",
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "HookResult",
    "DecisionRegistry",
    "HookRegistry",
    "Event",
    "UserInput",
    "UserInputDecision",
    "AgentStart",
    "AgentStartDecision",
    "AgentEnd",
    "TurnStart",
    "BeforeModelCall",
    "BeforeModelCallDecision",
    "ToolCallDecision",
    "ToolResultDecision",
    "TurnEnd",
    "MessageStart",
    "MessageUpdate",
    "MessageEnd",
    "ToolExecutionStart",
    "ToolExecutionUpdate",
    "ToolExecutionEnd",
    "Session",
    "SessionTree",
    "SessionStore",
    "ContextManager",
    "ExtensionAPI",
    "ExtensionManager",
    "MemoryStore",
    "make_memory_tool",
    "TaskItem",
    "TaskStore",
    "ToolHistoryRepair",
    "repair_tool_history",
    "make_task_tools",
    "make_todo_tool",
    "SubagentTask",
    "SubagentTaskManager",
    "SubagentTaskStatus",
    "BackgroundJob",
    "BackgroundRunner",
    "MessageQueue",
    "MessageType",
    "QueuedMessage",
    "Plugin",
    "PluginAuthor",
    "PluginManifest",
    "PluginManager",
    "ContextCompacted",
    "ToolsChanged",
    "AgentEvent",
    "CancellationToken",
    "_provider_context",
    "run_agent_loop",
]
