from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

from my_agent_llm.models import Response
from my_coding_agent import CodingAgent
from my_coding_agent.permissions import PermissionGate, PermissionRequest
from my_agent_tui.cli import SLASH_COMMANDS, main
from my_agent_tui.commands import CommandDispatcher


class FakeLLM:
    async def achat(self, *a, **kw):
        return Response(content="ok", model="fake")

    async def achat_stream(self, *a, **kw):
        return
        yield


@pytest.mark.anyio
async def test_cmd_mode_switch(tmp_path: Path):
    buf = Console(record=True)
    gate = PermissionGate(mode="review")
    agent = CodingAgent(
        workspace=tmp_path,
        llm=FakeLLM(),
        session=tmp_path / "s.jsonl",
        permission_gate=gate,
    )
    dispatcher = CommandDispatcher(agent)

    # 1. 查当前模式
    await dispatcher.dispatch("/mode", buf)
    assert "review" in buf.export_text()

    # 2. 切 yolo 模式
    await dispatcher.dispatch("/mode yolo", buf)
    assert gate.mode == "autonomous"
    assert "yolo" in buf.export_text() or "autonomous" in buf.export_text()

    # 3. 切 strict 模式
    buf = Console(record=True)
    await dispatcher.dispatch("/mode strict", buf)
    assert gate.mode == "strict"
    assert "strict" in buf.export_text()

    # 4. 切 review 模式
    buf = Console(record=True)
    await dispatcher.dispatch("/mode review", buf)
    assert gate.mode == "review"
    assert "review" in buf.export_text()

    # 5. 切 autonomous 模式
    buf = Console(record=True)
    await dispatcher.dispatch("/mode autonomous", buf)
    assert gate.mode == "autonomous"
    assert "autonomous" in buf.export_text()

    # 6. 无效模式
    buf = Console(record=True)
    await dispatcher.dispatch("/mode invalid_mode", buf)
    assert gate.mode == "autonomous"  # 保持原状
    assert "无效" in buf.export_text() or "invalid_mode" in buf.export_text()


@pytest.mark.anyio
async def test_cmd_mode_without_gate(tmp_path: Path):
    buf = Console(record=True)
    agent = CodingAgent(
        workspace=tmp_path,
        llm=FakeLLM(),
        session=tmp_path / "s_nogate.jsonl",
        permission_gate=None,
    )
    dispatcher = CommandDispatcher(agent)

    await dispatcher.dispatch("/mode", buf)
    assert "未启用" in buf.export_text() or "PermissionGate" in buf.export_text()

    buf = Console(record=True)
    await dispatcher.dispatch("/mode yolo", buf)
    assert "未启用" in buf.export_text() or "无法切换" in buf.export_text()


def test_mode_in_slash_commands():
    assert "/mode" in SLASH_COMMANDS


def test_main_argparse_mode_and_gate_wiring(tmp_path: Path):
    captured_agent = None

    async def fake_run_cli_loop(agent: CodingAgent, console: Console):
        nonlocal captured_agent
        captured_agent = agent

    with patch("my_agent_tui.cli.run_cli_loop", side_effect=fake_run_cli_loop):
        main(
            argv=["--workspace", str(tmp_path), "--mode", "strict"],
            llm=FakeLLM(),  # type: ignore
        )

    assert captured_agent is not None
    assert captured_agent.permission_gate is not None
    assert captured_agent.permission_gate.mode == "strict"
    assert captured_agent.permission_gate.confirm_callback is not None


def test_main_confirm_callback_wiring(tmp_path: Path):
    captured_agent = None

    async def fake_run_cli_loop(agent: CodingAgent, console: Console):
        nonlocal captured_agent
        captured_agent = agent

    with patch("my_agent_tui.cli.run_cli_loop", side_effect=fake_run_cli_loop):
        main(
            argv=["--workspace", str(tmp_path), "--mode", "review"],
            llm=FakeLLM(),  # type: ignore
        )

    assert captured_agent is not None
    gate = captured_agent.permission_gate
    assert gate is not None
    assert gate.confirm_callback is not None

    async def _test_callbacks():
        # Test confirm callback invokes ConfirmView with details_text = preview or target
        with patch("my_agent_tui.components.confirm.ConfirmView.prompt_confirm", new_callable=AsyncMock) as mock_prompt:
            mock_prompt.return_value = True
            req_with_preview = PermissionRequest(
                action="write",
                target="a.py",
                preview="print('hello')",
            )
            cb_res = gate.confirm_callback(req_with_preview)
            res = await cb_res if inspect.isawaitable(cb_res) else cb_res
            assert res is True
            mock_prompt.assert_called_once()
            _, kwargs = mock_prompt.call_args
            assert kwargs["details_text"] == "print('hello')"

        with patch("my_agent_tui.components.confirm.ConfirmView.prompt_confirm", new_callable=AsyncMock) as mock_prompt:
            mock_prompt.return_value = False
            req_without_preview = PermissionRequest(
                action="bash",
                target="rm -rf /tmp/test",
                preview=None,
            )
            cb_res = gate.confirm_callback(req_without_preview)
            res = await cb_res if inspect.isawaitable(cb_res) else cb_res
            assert res is False
            mock_prompt.assert_called_once()
            _, kwargs = mock_prompt.call_args
            assert kwargs["details_text"] == "rm -rf /tmp/test"

    import asyncio

    asyncio.run(_test_callbacks())
