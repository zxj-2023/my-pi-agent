from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from my_agent_core.events import AgentEnd, MessageUpdate
from my_agent_llm.models import Message, Response, StreamChunk
from my_coding_agent import CodingAgent
from my_agent_tui.cli import run_cli_loop


class FakeLLM:
    def __init__(self, model: str = "fake"):
        self.model = model

    async def achat(self, *a, **kw):
        return Response(content="ok", model=self.model)

    async def achat_stream(self, *a, **kw):
        pass


@pytest.mark.anyio
async def test_cli_renders_footer_in_loop(tmp_path: Path):
    console = Console(record=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["/exit"])

    await run_cli_loop(agent, console, prompt_session=mock_session)
    out = console.export_text()
    assert "📁" in out
    assert "🌿" in out
    assert "fake" in out
    assert "Tokens:" in out


@pytest.mark.anyio
async def test_cli_streaming_live_steering_and_abort(tmp_path: Path):
    console = Console(record=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    captured_listeners = []

    class MockLiveInputListener:
        def __init__(self, on_escape=None, on_line=None):
            self.on_escape = on_escape
            self.on_line = on_line
            captured_listeners.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    async def fake_stream(prompt: str):
        assert len(captured_listeners) == 1
        listener = captured_listeners[0]

        # 1. 模拟从后台按键监听线程注入即时转向指令
        t_steer = threading.Thread(target=listener.on_line, args=("请改用 pytest 编写测试",))
        t_steer.start()
        t_steer.join()

        # 等待事件循环调度 threadsafe 任务
        await asyncio.sleep(0.02)

        # 2. 模拟从后台按键监听线程按下 ESC 中止流式生成
        t_abort = threading.Thread(target=listener.on_escape)
        t_abort.start()
        t_abort.join()

        await asyncio.sleep(0.02)

        yield MessageUpdate(
            message=Message(role="assistant", content=""),
            chunk=StreamChunk(content="streaming chunk"),
        )
        yield AgentEnd(stop_reason="end_turn", iterations=1)

    agent.run_stream = fake_stream  # type: ignore

    with patch("my_agent_tui.cli.LiveInputListener", MockLiveInputListener), \
         patch.object(agent, "steer") as mock_steer, \
         patch.object(agent, "abort") as mock_abort:

        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(side_effect=["实现功能", "/exit"])

        await run_cli_loop(agent, console, prompt_session=mock_session)

        mock_steer.assert_called_once_with("请改用 pytest 编写测试")
        mock_abort.assert_called_once()
        out = console.export_text()
        assert "已注入即时转向指令: 请改用 pytest 编写测试" in out


@pytest.mark.anyio
async def test_cli_streaming_live_steering_and_abort_direct(tmp_path: Path):
    console = Console(record=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    captured_listeners = []

    class MockLiveInputListener:
        def __init__(self, on_escape=None, on_line=None):
            self.on_escape = on_escape
            self.on_line = on_line
            captured_listeners.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    async def fake_stream(prompt: str):
        listener = captured_listeners[0]
        # 直接同线程调用回调
        listener.on_line("直接转向指令")
        listener.on_escape()
        yield MessageUpdate(
            message=Message(role="assistant", content=""),
            chunk=StreamChunk(content="chunk"),
        )
        yield AgentEnd(stop_reason="end_turn", iterations=1)

    agent.run_stream = fake_stream  # type: ignore

    with patch("my_agent_tui.cli.LiveInputListener", MockLiveInputListener), \
         patch.object(agent, "steer") as mock_steer, \
         patch.object(agent, "abort") as mock_abort:

        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(side_effect=["测试直接调用", "/exit"])

        await run_cli_loop(agent, console, prompt_session=mock_session)

        mock_steer.assert_called_once_with("直接转向指令")
        mock_abort.assert_called_once()
        out = console.export_text()
        assert "已注入即时转向指令: 直接转向指令" in out

