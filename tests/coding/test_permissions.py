from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from my_agent_core.hooks import ToolCallHook

from my_coding_agent.permissions import PermissionGate, PermissionRequest


@pytest.mark.anyio
async def test_permission_gate_readonly_tools_always_allowed():
    mock_cb = AsyncMock(return_value=False)
    gate = PermissionGate(mode="review", confirm_callback=mock_cb)

    for tool_name in ("read", "grep", "find"):
        hook = ToolCallHook(tool_call_id="c1", tool_name=tool_name, args={"path": "a.txt"})
        result = await gate(hook)
        assert result.block is False
    mock_cb.assert_not_called()


@pytest.mark.anyio
async def test_permission_gate_yolo_mode_allows_all():
    mock_cb = AsyncMock(return_value=False)
    gate = PermissionGate(mode="yolo", confirm_callback=mock_cb)
    hook = ToolCallHook(
        tool_call_id="c2",
        tool_name="write",
        args={"path": "a.txt", "content": "123"},
    )
    result = await gate(hook)
    assert result.block is False
    mock_cb.assert_not_called()


@pytest.mark.anyio
async def test_permission_gate_autonomous_mode_allows_all():
    mock_cb = AsyncMock(return_value=False)
    gate = PermissionGate(mode="autonomous", confirm_callback=mock_cb)
    hook = ToolCallHook(
        tool_call_id="c2_auto",
        tool_name="bash",
        args={"command": "rm -rf /"},
    )
    result = await gate(hook)
    assert result.block is False
    mock_cb.assert_not_called()


@pytest.mark.anyio
async def test_permission_gate_safe_bash_commands_allowed():
    mock_cb = AsyncMock(return_value=False)
    gate = PermissionGate(mode="review", confirm_callback=mock_cb)

    safe_cmds = [
        "git status",
        "git diff main",
        "git log -n 5",
        "pytest -q",
        "python -m pytest tests/",
        "uv run pytest",
    ]
    for cmd in safe_cmds:
        hook = ToolCallHook(tool_call_id="c_safe", tool_name="bash", args={"command": cmd})
        result = await gate(hook)
        assert result.block is False
    mock_cb.assert_not_called()


@pytest.mark.anyio
async def test_permission_gate_review_mode_prompts_write():
    captured_req: PermissionRequest | None = None

    async def cb(req: PermissionRequest) -> bool:
        nonlocal captured_req
        captured_req = req
        return True

    gate = PermissionGate(mode="review", confirm_callback=cb)
    hook = ToolCallHook(
        tool_call_id="c3",
        tool_name="write",
        args={"path": "a.txt", "content": "hello world"},
    )
    result = await gate(hook)
    assert result.block is False
    assert captured_req is not None
    assert captured_req.action == "write"
    assert captured_req.target == "a.txt"
    assert captured_req.preview == "hello world"
    assert captured_req.details == {"path": "a.txt", "content": "hello world"}


@pytest.mark.anyio
async def test_permission_gate_review_mode_prompts_edit():
    captured_req: PermissionRequest | None = None

    async def cb(req: PermissionRequest) -> bool:
        nonlocal captured_req
        captured_req = req
        return True

    gate = PermissionGate(mode="review", confirm_callback=cb)
    hook = ToolCallHook(
        tool_call_id="c3_edit",
        tool_name="edit",
        args={"path": "src/main.py", "edits": [{"oldText": "a", "newText": "b"}]},
    )
    result = await gate(hook)
    assert result.block is False
    assert captured_req is not None
    assert captured_req.action == "edit"
    assert captured_req.target == "src/main.py"
    assert captured_req.preview == "[{'oldText': 'a', 'newText': 'b'}]"


@pytest.mark.anyio
async def test_permission_gate_review_mode_prompts_unsafe_bash():
    mock_cb = AsyncMock(return_value=True)
    gate = PermissionGate(mode="review", confirm_callback=mock_cb)
    hook = ToolCallHook(
        tool_call_id="c_unsafe",
        tool_name="bash",
        args={"command": "rm -rf /tmp/test"},
    )
    result = await gate(hook)
    assert result.block is False
    mock_cb.assert_called_once()
    req = mock_cb.call_args[0][0]
    assert req.action == "bash"
    assert req.target == "rm -rf /tmp/test"


@pytest.mark.anyio
async def test_permission_gate_denial_blocks_tool():
    mock_cb = AsyncMock(return_value=False)
    gate = PermissionGate(mode="review", confirm_callback=mock_cb)
    hook = ToolCallHook(
        tool_call_id="c4",
        tool_name="write",
        args={"path": "a.txt", "content": "123"},
    )
    result = await gate(hook)
    assert result.block is True
    assert "用户拒绝了工具 [write] 的执行请求。" in (result.reason or "")


@pytest.mark.anyio
async def test_permission_gate_no_callback_allows_by_default():
    gate = PermissionGate(mode="review", confirm_callback=None)
    hook = ToolCallHook(
        tool_call_id="c5",
        tool_name="write",
        args={"path": "a.txt", "content": "123"},
    )
    result = await gate(hook)
    assert result.block is False


@pytest.mark.anyio
async def test_permission_gate_strict_mode_blocks_readonly_without_approval():
    mock_cb = AsyncMock(return_value=False)
    gate = PermissionGate(mode="strict", confirm_callback=mock_cb)
    hook = ToolCallHook(
        tool_call_id="c6",
        tool_name="read",
        args={"path": "secret.txt"},
    )
    result = await gate(hook)
    assert result.block is True
    assert "用户拒绝了工具 [read] 的执行请求。" in (result.reason or "")
    mock_cb.assert_called_once()


@pytest.mark.anyio
async def test_permission_gate_sync_callback_supported():
    def sync_cb(req: PermissionRequest) -> bool:
        return False

    gate = PermissionGate(mode="review", confirm_callback=sync_cb)
    hook = ToolCallHook(
        tool_call_id="c7",
        tool_name="write",
        args={"path": "a.txt", "content": "123"},
    )
    result = await gate(hook)
    assert result.block is True
    assert "用户拒绝了工具 [write] 的执行请求。" in (result.reason or "")
