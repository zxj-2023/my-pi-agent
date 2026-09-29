"""``PermissionGate`` 与 ACP ``session/request_permission`` 的桥接。

``my_coding_agent.permissions.PermissionGate`` 早已预留 ``confirm_callback`` 交互审批
扩展点，但 TUI 链路从未注入过它（走的是纯模式判定）。ACP 恰好提供了标准的反向
审批通道，本模块把两者接起来：

    PermissionGate.confirm_callback  →  AcpPermissionBridge
                                          ↓
                          conn.request_permission(...)  →  编辑器弹窗
                                          ↓
                          allow_once / allow_always / reject_*

编辑器返回的 ``allow_always`` / ``reject_always`` 会被记住，避免同一会话内反复弹窗。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from acp.schema import (
    PermissionOption,
    RequestPermissionResponse,
    ToolCallUpdate,
)
from my_coding_agent.permissions import PermissionRequest

from my_acp_agent.events import tool_kind, tool_locations, tool_title

if TYPE_CHECKING:
    from pathlib import Path

    from acp import AgentSideConnection

__all__ = ["AcpPermissionBridge", "build_permission_options"]

#: 四个标准 ACP 审批选项。
_OPTIONS = [
    PermissionOption(option_id="allow_once", name="Allow once", kind="allow_once"),
    PermissionOption(option_id="allow_always", name="Allow always", kind="allow_always"),
    PermissionOption(option_id="reject_once", name="Reject once", kind="reject_once"),
    PermissionOption(option_id="reject_always", name="Reject always", kind="reject_always"),
]

_ALLOWED = frozenset({"allow_once", "allow_always"})
_REMEMBERED = frozenset({"allow_always", "reject_always"})


def build_permission_options() -> list[PermissionOption]:
    """返回标准审批选项列表（每次调用返回新副本，避免调用方误改共享实例）。"""
    return list(_OPTIONS)


class AcpPermissionBridge:
    """把 ``PermissionGate`` 的审批回调转成 ACP 反向请求。

    每个 ACP 会话对应一个实例：审批记忆按会话隔离，会话关闭即失效。
    """

    def __init__(self, session_id: str, workspace: Path) -> None:
        self.session_id = session_id
        self.workspace = workspace
        self.conn: AgentSideConnection | None = None
        self._remembered: dict[str, bool] = {}

    def bind(self, conn: AgentSideConnection) -> None:
        """绑定 ACP 连接（由 ``AcpAgent.on_connect`` 注入）。"""
        self.conn = conn

    async def confirm(self, request: PermissionRequest) -> bool:
        """``PermissionGate.confirm_callback`` 的实现。

        连接尚未就绪时保守放行 —— 与 ``PermissionGate`` 无回调时的既有语义保持一致。
        """
        if self.conn is None:
            return True

        remembered = self._remembered.get(request.action)
        if remembered is not None:
            return remembered

        tool_call = ToolCallUpdate(
            tool_call_id=f"perm-{request.action}-{abs(hash(request.target)) & 0xFFFFFF:06x}",
            title=tool_title(request.action, request.details),
            kind=tool_kind(request.action),
            status="pending",
            locations=tool_locations(request.action, request.details, self.workspace),
            raw_input=request.details or None,
        )

        try:
            response: RequestPermissionResponse = await self.conn.request_permission(
                session_id=self.session_id,
                tool_call=tool_call,
                options=build_permission_options(),
            )
        except Exception:
            # 编辑器侧取消/断连时保守拒绝，避免在无人值守下静默执行写操作。
            return False

        return self._resolve(response, request.action)

    def _resolve(self, response: RequestPermissionResponse, action: str) -> bool:
        outcome = getattr(response, "outcome", None)
        if outcome is None or getattr(outcome, "outcome", None) != "selected":
            return False

        option_id = getattr(outcome, "option_id", "")
        allowed = option_id in _ALLOWED
        if option_id in _REMEMBERED:
            self._remembered[action] = allowed
        return allowed
