"""AcpPermissionBridge 与 PermissionGate 的集成单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse
from my_agent_core.hooks import ToolCallHook

from my_acp_agent.permissions import AcpPermissionBridge, build_permission_options
from my_coding_agent.permissions import PermissionGate, PermissionRequest

WS = Path("/workspace")


def _allowed(option_id: str) -> RequestPermissionResponse:
    return RequestPermissionResponse(outcome=AllowedOutcome(outcome="selected", option_id=option_id))


def _denied() -> RequestPermissionResponse:
    return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


def _bridge_with(response) -> tuple[AcpPermissionBridge, AsyncMock]:
    bridge = AcpPermissionBridge(session_id="s1", workspace=WS)
    conn = AsyncMock()
    conn.request_permission = AsyncMock(return_value=response)
    bridge.bind(conn)
    return bridge, conn


def test_build_permission_options_returns_four_standard_kinds():
    options = build_permission_options()
    assert [o.kind for o in options] == ["allow_once", "allow_always", "reject_once", "reject_always"]
    # 每次返回新副本，调用方修改不污染模块级常量
    options.pop()
    assert len(build_permission_options()) == 4


@pytest.mark.anyio
async def test_bridge_allows_when_connection_missing():
    """连接未就绪时保守放行，与 PermissionGate 无回调时的既有语义一致。"""
    bridge = AcpPermissionBridge(session_id="s1", workspace=WS)
    assert await bridge.confirm(PermissionRequest(action="write", target="a.py")) is True


@pytest.mark.anyio
async def test_bridge_allow_once_does_not_remember():
    bridge, conn = _bridge_with(_allowed("allow_once"))
    req = PermissionRequest(action="write", target="a.py")

    assert await bridge.confirm(req) is True
    assert await bridge.confirm(req) is True
    assert conn.request_permission.await_count == 2


@pytest.mark.anyio
async def test_bridge_allow_always_is_remembered():
    bridge, conn = _bridge_with(_allowed("allow_always"))
    req = PermissionRequest(action="write", target="a.py")

    assert await bridge.confirm(req) is True
    assert await bridge.confirm(req) is True
    assert conn.request_permission.await_count == 1


@pytest.mark.anyio
async def test_bridge_reject_always_is_remembered():
    bridge, conn = _bridge_with(_allowed("reject_always"))
    req = PermissionRequest(action="bash", target="rm -rf /")

    assert await bridge.confirm(req) is False
    assert await bridge.confirm(req) is False
    assert conn.request_permission.await_count == 1


@pytest.mark.anyio
async def test_bridge_denied_outcome_rejects():
    bridge, _ = _bridge_with(_denied())
    assert await bridge.confirm(PermissionRequest(action="write", target="a.py")) is False


@pytest.mark.anyio
async def test_bridge_request_failure_rejects_conservatively():
    """编辑器断连/取消时保守拒绝，避免无人值守下静默执行写操作。"""
    bridge = AcpPermissionBridge(session_id="s1", workspace=WS)
    conn = AsyncMock()
    conn.request_permission = AsyncMock(side_effect=RuntimeError("connection closed"))
    bridge.bind(conn)

    assert await bridge.confirm(PermissionRequest(action="write", target="a.py")) is False


@pytest.mark.anyio
async def test_bridge_forwards_tool_metadata_to_client():
    bridge, conn = _bridge_with(_allowed("allow_once"))
    await bridge.confirm(
        PermissionRequest(action="bash", target="ls -la", details={"command": "ls -la"})
    )

    kwargs = conn.request_permission.await_args.kwargs
    assert kwargs["session_id"] == "s1"
    assert kwargs["tool_call"].kind == "execute"
    assert kwargs["tool_call"].title == "Run ls -la"
    assert [o.kind for o in kwargs["options"]] == ["allow_once", "allow_always", "reject_once", "reject_always"]


@pytest.mark.anyio
async def test_gate_blocks_when_bridge_rejects():
    """端到端：编辑器拒绝 → PermissionGate 返回 block。"""
    bridge, _ = _bridge_with(_allowed("reject_once"))
    gate = PermissionGate(mode="review", confirm_callback=bridge.confirm)

    result = await gate(ToolCallHook(tool_call_id="c1", tool_name="write", args={"path": "a.py", "content": "x"}))
    assert result.block is True
    assert "拒绝" in (result.reason or "")


@pytest.mark.anyio
async def test_gate_allows_when_bridge_approves():
    bridge, _ = _bridge_with(_allowed("allow_once"))
    gate = PermissionGate(mode="review", confirm_callback=bridge.confirm)

    result = await gate(ToolCallHook(tool_call_id="c1", tool_name="write", args={"path": "a.py", "content": "x"}))
    assert result.block is False


@pytest.mark.anyio
async def test_gate_readonly_tools_never_reach_bridge():
    """只读工具在门禁层直接放行，不产生 ACP 弹窗。"""
    bridge, conn = _bridge_with(_allowed("allow_once"))
    gate = PermissionGate(mode="review", confirm_callback=bridge.confirm)

    result = await gate(ToolCallHook(tool_call_id="c1", tool_name="read", args={"path": "a.py"}))
    assert result.block is False
    conn.request_permission.assert_not_awaited()
