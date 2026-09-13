from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from rich.console import Console

from prompt_toolkit.document import Document
from my_coding_agent import CodingAgent
from my_agent_tui.cli import build_prompt_session, run_cli_loop
from my_agent_tui.components.completer import FileReferenceCompleter
from my_agent_llm.models import Response


class FakeLLM:
    async def achat(self, *a, **kw):
        return Response(content="ok", model="fake")

    async def achat_stream(self, *a, **kw):
        pass


@pytest.mark.anyio
async def test_cli_loop_expands_file_reference(tmp_path: Path):
    target = tmp_path / "app.py"
    target.write_text("print('core code')\n", encoding="utf-8")

    captured_prompt = None

    async def mock_run_stream(prompt: str):
        nonlocal captured_prompt
        captured_prompt = prompt
        yield  # generator

    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    agent.run_stream = mock_run_stream  # type: ignore

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["请查看 @app.py", "/exit"])
    console = Console(file=None)

    await run_cli_loop(agent, console, prompt_session=mock_session)

    assert captured_prompt is not None
    assert "<referenced_files>" in captured_prompt
    assert "print('core code')" in captured_prompt


@pytest.mark.anyio
async def test_cli_loop_calls_close_mcp(tmp_path: Path):
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    agent.close_mcp = AsyncMock()  # type: ignore

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["/exit"])
    console = Console(file=None)

    await run_cli_loop(agent, console, prompt_session=mock_session)

    agent.close_mcp.assert_awaited_once()


@pytest.mark.anyio
async def test_cli_loop_calls_close_mcp_on_exception(tmp_path: Path):
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    agent.close_mcp = AsyncMock()  # type: ignore

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=RuntimeError("unexpected prompt error"))
    console = Console(file=None)

    with pytest.raises(RuntimeError, match="unexpected prompt error"):
        await run_cli_loop(agent, console, prompt_session=mock_session)

    agent.close_mcp.assert_awaited_once()


@pytest.mark.anyio
async def test_cli_loop_graceful_without_close_mcp(tmp_path: Path):
    agent = MagicMock(spec=["workspace", "run_stream"])
    agent.workspace = tmp_path

    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock(side_effect=["/exit"])
    console = Console(file=None)

    await run_cli_loop(agent, console, prompt_session=mock_session)


def test_build_prompt_session_file_reference_completer(tmp_path: Path):
    target = tmp_path / "index.js"
    target.write_text("console.log('hello');", encoding="utf-8")

    session = build_prompt_session(tmp_path)
    assert isinstance(session.completer, FileReferenceCompleter)

    # 验证 @ 文件自动补全能力
    doc_at = Document("@ind", 4)
    completions_at = [c.text for c in session.completer.get_completions(doc_at, None)]
    assert "@index.js" in completions_at

    # 验证基础斜杠命令补全能力
    doc_slash = Document("/ex", 3)
    completions_slash = [c.text for c in session.completer.get_completions(doc_slash, None)]
    assert "/exit" in completions_slash
