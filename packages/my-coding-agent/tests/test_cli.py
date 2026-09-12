"""Unit tests for CLI REPL and entrypoint."""

from __future__ import annotations

import asyncio
import io
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.document import Document
from rich.console import Console

from my_agent_core.events import AgentEnd, MessageUpdate
from my_agent_llm.models import Message, Response, StreamChunk

from my_coding_agent.agent import CodingAgent
from my_coding_agent.cli import SLASH_COMMANDS, build_prompt_session, main, run_cli_loop


class FakeLLM:
    async def achat(self, *a, **kw):
        return Response(content="ok", model="fake")

    async def achat_stream(self, *a, **kw):
        yield StreamChunk(content="chunk")


def test_build_prompt_session(tmp_path: Path):
    session = build_prompt_session(tmp_path)
    assert session is not None
    assert session.completer is not None

    hist_dir = tmp_path / ".my_agent_core"
    assert hist_dir.is_dir()

    # Verify completer provides slash commands
    doc = Document("/he", 3)
    completions = [c.text for c in session.completer.get_completions(doc, None)]
    assert "/help" in completions
    assert set(SLASH_COMMANDS).issuperset({"/help", "/clear", "/undo", "/compact", "/session", "/tasks", "/mcp", "/exit", "/quit"})


@pytest.mark.anyio
async def test_run_cli_loop_exit(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["/exit"])

    await run_cli_loop(agent, console, prompt_session=mock_session)

    out = buf.getvalue()
    assert "my-coding-agent 终端编程助手" in out
    assert "正在退出" in out or "再见" in out


@pytest.mark.anyio
async def test_run_cli_loop_eof(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=EOFError())

    await run_cli_loop(agent, console, prompt_session=mock_session)

    out = buf.getvalue()
    assert "再见！" in out


@pytest.mark.anyio
async def test_run_cli_loop_keyboard_interrupt(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=KeyboardInterrupt())

    await run_cli_loop(agent, console, prompt_session=mock_session)

    out = buf.getvalue()
    assert "再见！" in out


@pytest.mark.anyio
async def test_run_cli_loop_empty_and_whitespace(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["   ", "", "/exit"])

    await run_cli_loop(agent, console, prompt_session=mock_session)

    out = buf.getvalue()
    assert "my-coding-agent 终端编程助手" in out


@pytest.mark.anyio
async def test_run_cli_loop_dispatches_help(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["/help", "/exit"])

    await run_cli_loop(agent, console, prompt_session=mock_session)

    out = buf.getvalue()
    assert "/help" in out
    assert "/undo" in out
    assert "/compact" in out


@pytest.mark.anyio
async def test_run_cli_loop_runs_stream(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    async def fake_stream(prompt: str):
        yield MessageUpdate(message=Message(role="assistant", content=""), chunk=StreamChunk(content="Hello from agent!"))
        yield AgentEnd(stop_reason="end_turn", iterations=1)

    agent.run_stream = fake_stream  # type: ignore

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["Explain Python", "/exit"])

    await run_cli_loop(agent, console, prompt_session=mock_session)

    out = buf.getvalue()
    assert "Hello from agent!" in out


@pytest.mark.anyio
async def test_run_cli_loop_cancelled_error(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    async def cancelling_stream(prompt: str):
        raise asyncio.CancelledError()
        yield  # make it an async generator

    agent.run_stream = cancelling_stream  # type: ignore

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["trigger cancel", "/exit"])

    await run_cli_loop(agent, console, prompt_session=mock_session)

    out = buf.getvalue()
    assert "已取消当前生成轮次" in out


@pytest.mark.anyio
async def test_run_cli_loop_generic_error(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    async def failing_stream(prompt: str):
        raise RuntimeError("LLM network timeout")
        yield

    agent.run_stream = failing_stream  # type: ignore

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["trigger error", "/exit"])

    await run_cli_loop(agent, console, prompt_session=mock_session)

    out = buf.getvalue()
    assert "运行出错: LLM network timeout" in out


def test_main_argparse_and_invocation(tmp_path: Path):
    captured_agent = None

    async def fake_run_cli_loop(agent: CodingAgent, console: Console):
        nonlocal captured_agent
        captured_agent = agent

    with patch("my_coding_agent.cli.run_cli_loop", side_effect=fake_run_cli_loop):
        main(
            argv=["--workspace", str(tmp_path), "--model", "custom-gpt"],
            llm=FakeLLM(),  # type: ignore
        )

    assert captured_agent is not None
    assert captured_agent.workspace == tmp_path.resolve()
    assert captured_agent.session.path == tmp_path.resolve() / ".my_agent_core" / "sessions" / "default_session.jsonl"


def test_module_python_m_help():
    result = subprocess.run(
        [sys.executable, "-m", "my_coding_agent", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert "my-coding-agent 交互式编码助手" in result.stdout
    assert "--workspace" in result.stdout
    assert "--model" in result.stdout
