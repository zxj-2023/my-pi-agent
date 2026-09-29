"""ACP 端到端冒烟脚本：以真实 stdio 子进程方式驱动 my_acp_agent.server。

用法：
    uv run python scripts/acp_smoke.py

它会拉起 `python -m my_acp_agent.server` 子进程，走完整的 JSON-RPC 握手，
验证 initialize / session/new / session/prompt 链路是否通畅。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from acp import PROTOCOL_VERSION, Client, spawn_agent_process
from acp.schema import (
    AgentMessageChunk,
    RequestPermissionResponse,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)


class SmokeClient(Client):
    """最小 ACP 客户端：打印收到的所有 session/update，权限一律拒绝。"""

    def __init__(self) -> None:
        self.updates: list[str] = []

    async def session_update(self, session_id: str, update, **kwargs) -> None:
        kind = getattr(update, "session_update", "?")
        if isinstance(update, AgentMessageChunk):
            self.updates.append(f"agent_message: {update.content.text!r}")
        elif isinstance(update, ToolCallStart):
            self.updates.append(f"tool_call: {update.title} [{update.kind}]")
        elif isinstance(update, ToolCallProgress):
            self.updates.append(f"tool_update: {update.status}")
        else:
            self.updates.append(f"{kind}")

    async def request_permission(self, session_id, tool_call, options, **kwargs) -> RequestPermissionResponse:
        from acp.schema import DeniedOutcome

        return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


async def main() -> int:
    workspace = Path(__file__).resolve().parent.parent
    client = SmokeClient()

    async with spawn_agent_process(
        client,
        sys.executable,
        "-m",
        "my_acp_agent.server",
        "--workspace",
        str(workspace),
    ) as (conn, _proc):
        init = await conn.initialize(protocol_version=PROTOCOL_VERSION)
        print(f"[1] initialize → protocol={init.protocol_version} agent={init.agent_info.name}")

        session = await conn.new_session(cwd=str(workspace))
        print(f"[2] session/new → {session.session_id}")

        result = await conn.prompt(
            session_id=session.session_id,
            prompt=[TextContentBlock(type="text", text="Reply with exactly: ACP OK")],
        )
        print(f"[3] session/prompt → stop_reason={result.stop_reason}")

        print(f"[4] 收到 {len(client.updates)} 条 session/update:")
        for line in client.updates[:20]:
            print(f"      - {line}")

        await conn.close_session(session_id=session.session_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
