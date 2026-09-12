"""Unit tests for slash commands dispatcher and built-in commands."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from my_agent_core.session import Session
from my_agent_core.task_store import TaskStore
from my_agent_core.tools import Tool, ToolResult
from my_agent_llm.models import Response

from my_coding_agent.agent import CodingAgent
from my_agent_tui.commands import CommandContext, CommandDispatcher


class FakeLLM:
    async def achat(self, *a, **kw):
        return Response(content="ok", model="fake")

    async def achat_stream(self, *a, **kw):
        return
        yield


@pytest.mark.anyio
async def test_commands_help(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/help", console)
    assert handled is True
    assert "/undo" in buf.getvalue()
    assert "/compact" in buf.getvalue()
    assert "/tasks" in buf.getvalue()
    assert "/mcp" in buf.getvalue()


@pytest.mark.anyio
async def test_commands_undo_empty(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/undo", console)
    assert handled is True
    assert "无法撤销" in buf.getvalue() or "最初状态" in buf.getvalue()


@pytest.mark.anyio
async def test_commands_non_slash(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("hello world", console)
    assert handled is False


@pytest.mark.anyio
async def test_commands_unknown(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/unknown_command", console)
    assert handled is True
    assert "未知命令" in buf.getvalue()
    assert "/unknown_command" in buf.getvalue()


@pytest.mark.anyio
async def test_commands_exit_and_quit(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    assert dispatcher.exit_requested is False
    handled = await dispatcher.dispatch("/exit", console)
    assert handled is True
    assert dispatcher.exit_requested is True
    assert "再见" in buf.getvalue()

    dispatcher.exit_requested = False
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    handled = await dispatcher.dispatch("/quit", console)
    assert handled is True
    assert dispatcher.exit_requested is True
    assert "再见" in buf.getvalue()


@pytest.mark.anyio
async def test_commands_clear(tmp_path: Path):
    mock_console = MagicMock(spec=Console)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/clear", mock_console)
    assert handled is True
    mock_console.clear.assert_called_once()


@pytest.mark.anyio
async def test_commands_session(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, width=500)
    session_file = tmp_path / "s.jsonl"
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=session_file)
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/session", console)
    assert handled is True
    out = buf.getvalue()
    assert "会话 ID" in out
    assert "持久化路径" in out
    assert "s.jsonl" in out
    assert str(session_file) in out


@pytest.mark.anyio
async def test_commands_compact(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/compact", console)
    assert handled is True
    out = buf.getvalue()
    assert "上下文压缩完成" in out or "智能上下文压缩" in out


@pytest.mark.anyio
async def test_commands_tasks(tmp_path: Path):
    # Case 1: No task store
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/tasks", console)
    assert handled is True
    assert "未启用 TaskStore" in buf.getvalue()

    # Case 2: With task store - empty
    ts = TaskStore(workspace=tmp_path)
    agent_with_ts = CodingAgent(
        workspace=tmp_path,
        llm=FakeLLM(),
        session=tmp_path / "s2.jsonl",
        task_store=ts,
    )
    dispatcher_ts = CommandDispatcher(agent_with_ts)

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    handled = await dispatcher_ts.dispatch("/tasks", console)
    assert handled is True
    assert "当前没有待办任务" in buf.getvalue()

    # Case 3: With task store - with tasks
    await ts.create(subject="Write unit tests", description="test tasks command")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    handled = await dispatcher_ts.dispatch("/tasks", console)
    assert handled is True
    assert "Write unit tests" in buf.getvalue()


@pytest.mark.anyio
async def test_commands_mcp(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    # Add a mock MCP tool
    mock_mcp_tool = Tool(
        func=lambda: ToolResult(ok=True, data="mcp output"),
        name="mcp_test_tool",
        description="A test MCP tool",
    )
    setattr(mock_mcp_tool, "is_mcp", True)
    agent.agent.registry.register(mock_mcp_tool)

    dispatcher = CommandDispatcher(agent)
    handled = await dispatcher.dispatch("/mcp", console)
    assert handled is True
    out = buf.getvalue()
    assert "已挂载 MCP 工具数: 1" in out
    assert "mcp_test_tool" in out


@pytest.mark.anyio
async def test_commands_custom_register(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    recorded_args = []

    async def custom_echo(ctx: CommandContext):
        recorded_args.append(ctx.raw_args)
        ctx.console.print(f"ECHO: {ctx.raw_args}")

    dispatcher.register("echo", custom_echo, "Echo args")
    handled = await dispatcher.dispatch("/echo foo bar", console)
    assert handled is True
    assert recorded_args == ["foo bar"]
    assert "ECHO: foo bar" in buf.getvalue()


@pytest.mark.anyio
async def test_commands_undo_multiple_turns(tmp_path: Path):
    session = Session(path=tmp_path / "s_turns.jsonl")
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=session)
    dispatcher = CommandDispatcher(agent)

    # Run two turns
    await agent.run("Turn 1 message")
    await agent.run("Turn 2 message")

    assert len(agent.session.tree.get_current_path()) >= 4  # 2 user + 2 assistant entries

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    handled = await dispatcher.dispatch("/undo", console)
    assert handled is True
    assert "已成功回退至节点" in buf.getvalue()


@pytest.mark.anyio
async def test_commands_faulty_handler_does_not_crash(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    def faulty_cmd(ctx: CommandContext):
        raise RuntimeError("Something exploded!")

    dispatcher.register("fail", faulty_cmd, "Fails intentionally")
    handled = await dispatcher.dispatch("/fail", console)
    assert handled is True
    assert "执行命令 /fail 失败: Something exploded!" in buf.getvalue()


@pytest.mark.anyio
async def test_commands_register_case_insensitive(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    dispatcher.register("/TESTCMD", lambda ctx: ctx.console.print("CALLED"), "Uppercase cmd")
    handled = await dispatcher.dispatch("/testcmd", console)
    assert handled is True
    assert "CALLED" in buf.getvalue()
