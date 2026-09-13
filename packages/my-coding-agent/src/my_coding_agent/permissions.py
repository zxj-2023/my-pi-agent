"""业务权限门禁（PermissionGate）：基于 ToolCallHook 实现的无侵入安全审批门禁。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from my_agent_core.hooks import HookResult, ToolCallHook

PermissionMode = Literal["review", "autonomous", "yolo", "strict"]
READONLY_TOOLS = frozenset({"read", "grep", "find"})
SAFE_BASH_PREFIXES = (
    "git status",
    "git diff",
    "git log",
    "pytest",
    "python -m pytest",
    "uv run",
)


@dataclass(frozen=True)
class PermissionRequest:
    """权限审批请求对象。"""

    action: str
    target: str
    details: dict[str, Any] = field(default_factory=dict)
    preview: str | None = None


class PermissionGate:
    """基于 ToolCallHook 实现的无侵入安全审批门禁。"""

    def __init__(
        self,
        mode: PermissionMode = "review",
        confirm_callback: Callable[[PermissionRequest], Awaitable[bool] | bool] | None = None,
    ) -> None:
        self.mode: PermissionMode = "autonomous" if mode == "yolo" else mode
        self.confirm_callback = confirm_callback

    async def __call__(self, hook: ToolCallHook) -> HookResult:
        if self.mode == "autonomous":
            return HookResult()

        tool_name = hook.tool_name
        args = hook.args or {}

        # 1. 只读工具放行 (除非 strict 模式)
        if self.mode != "strict" and tool_name in READONLY_TOOLS:
            return HookResult()

        # 2. 安全 Shell 命令放行
        if tool_name == "bash" and self.mode == "review":
            cmd = str(args.get("command", "")).strip()
            if any(cmd.startswith(p) for p in SAFE_BASH_PREFIXES):
                return HookResult()

        # 3. 发起用户交互审查
        if not self.confirm_callback:
            # 无交互回调时默认放行
            return HookResult()

        target = str(args.get("path") or args.get("command") or tool_name)
        preview = None
        if tool_name in ("write", "edit"):
            preview = args.get("content") or str(args.get("edits", ""))

        req = PermissionRequest(
            action=tool_name,
            target=target,
            details=args,
            preview=preview,
        )

        res = self.confirm_callback(req)
        approved = await res if inspect.isawaitable(res) else res
        if not approved:
            return HookResult(block=True, reason=f"用户拒绝了工具 [{tool_name}] 的执行请求。")

        return HookResult()
