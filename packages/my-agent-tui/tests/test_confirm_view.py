"""Tests for ConfirmView interactive terminal confirmation component."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

from my_agent_tui.components.confirm import ConfirmView


@pytest.mark.anyio
async def test_confirm_view_approve():
    confirm_view = ConfirmView(input_hook=AsyncMock(return_value="y"))
    res = await confirm_view.prompt_confirm("是否确认修改？", default=True)
    assert res is True

    confirm_view = ConfirmView(input_hook=AsyncMock(return_value="yes"))
    res = await confirm_view.prompt_confirm("是否确认修改？", default=False)
    assert res is True

    confirm_view = ConfirmView(input_hook=AsyncMock(return_value="1"))
    res = await confirm_view.prompt_confirm("是否确认修改？", default=False)
    assert res is True


@pytest.mark.anyio
async def test_confirm_view_deny():
    confirm_view = ConfirmView(input_hook=AsyncMock(return_value="n"))
    res = await confirm_view.prompt_confirm("是否确认修改？", default=True)
    assert res is False

    confirm_view = ConfirmView(input_hook=AsyncMock(return_value="no"))
    res = await confirm_view.prompt_confirm("是否确认修改？", default=True)
    assert res is False

    confirm_view = ConfirmView(input_hook=AsyncMock(return_value="other"))
    res = await confirm_view.prompt_confirm("是否确认修改？", default=True)
    assert res is False


@pytest.mark.anyio
async def test_confirm_view_default_enter():
    confirm_view = ConfirmView(input_hook=AsyncMock(return_value=""))
    res = await confirm_view.prompt_confirm("是否确认修改？", default=True)
    assert res is True

    confirm_view = ConfirmView(input_hook=AsyncMock(return_value="   "))
    res = await confirm_view.prompt_confirm("是否确认修改？", default=False)
    assert res is False


@pytest.mark.anyio
async def test_confirm_view_with_diff_details():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=80)
    confirm_view = ConfirmView(console=console, input_hook=AsyncMock(return_value="y"))

    diff_text = "--- a/test.py\n+++ b/test.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
    res = await confirm_view.prompt_confirm("是否应用上述 Diff？", default=True, details_text=diff_text)
    assert res is True
    output = buf.getvalue()
    assert "操作安全审查" in output
    assert "--- a/test.py" in output
    assert "+++ b/test.py" in output


@pytest.mark.anyio
async def test_confirm_view_with_plain_details():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=80)
    confirm_view = ConfirmView(console=console, input_hook=AsyncMock(return_value="n"))

    cmd_text = "rm -rf /tmp/test_dir"
    res = await confirm_view.prompt_confirm("是否执行危险命令？", default=False, details_text=cmd_text, title="危险命令拦截")
    assert res is False
    output = buf.getvalue()
    assert "危险命令拦截" in output
    assert "rm -rf /tmp/test_dir" in output


@pytest.mark.anyio
async def test_confirm_view_keyboard_interrupt():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=80)
    confirm_view = ConfirmView(console=console)

    with patch("builtins.input", side_effect=KeyboardInterrupt):
        res = await confirm_view.prompt_confirm("是否确认修改？", default=True)
        assert res is False
        assert "已取消操作" in buf.getvalue()


@pytest.mark.anyio
async def test_confirm_view_eof_error():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=80)
    confirm_view = ConfirmView(console=console)

    with patch("builtins.input", side_effect=EOFError):
        res = await confirm_view.prompt_confirm("是否确认修改？", default=True)
        assert res is False
        assert "已取消操作" in buf.getvalue()


@pytest.mark.anyio
async def test_confirm_view_executor_input():
    confirm_view = ConfirmView()

    with patch("builtins.input", return_value="y"):
        res = await confirm_view.prompt_confirm("确认？", default=False)
        assert res is True
