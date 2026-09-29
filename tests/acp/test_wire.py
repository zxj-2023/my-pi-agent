"""ACP 线级集成测试：真实 JSON-RPC 双端对接。

用内存 Transport 把 ``AcpAgent`` 与官方 ``ClientSideConnection`` 背靠背接起来，
跑完整的 initialize → session/new → session/prompt 链路，验证协议编解码、
方法路由与事件翻译在真实 JSON-RPC 帧上端到端成立（不经过 stdio 子进程）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from acp import PROTOCOL_VERSION, Client
from acp.agent.connection import AgentSideConnection
from acp.client.connection import ClientSideConnection
from acp.schema import (
    AgentMessageChunk,
    DeniedOutcome,
    RequestPermissionResponse,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)
from my_agent_llm.models import Response, StreamChunk, ToolCall

from my_acp_agent.agent import AcpAgent
from my_coding_agent.paths import AgentPaths


class MemoryTransport:
    """内存双向传输：两个端点互为对端，零 IO。"""

    def __init__(self) -> None:
        self._inbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.peer: MemoryTransport | None = None
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        assert self.peer is not None
        await self.peer._inbox.put(message)

    async def receive(self) -> dict[str, Any] | None:
        return await self._inbox.get()

    async def close(self) -> None:
        await self._inbox.put(None)


def _pair() -> tuple[MemoryTransport, MemoryTransport]:
    a, b = MemoryTransport(), MemoryTransport()
    a.peer, b.peer = b, a
    return a, b


class ScriptedLLM:
    def __init__(self, turns: list[dict[str, Any]]) -> None:
        self.turns = list(turns)
        self.idx = 0

    def _next(self) -> dict[str, Any]:
        payload = self.turns[self.idx] if self.idx < len(self.turns) else {"content": "done"}
        self.idx += 1
        return payload

    async def achat(self, messages, tools=None, **kwargs) -> Response:
        payload = self._next()
        return Response(
            content=payload.get("content", ""),
            model="fake",
            tool_calls=payload.get("tool_calls"),
        )

    async def achat_stream(self, messages, tools=None, **kwargs):
        payload = self._next()
        yield StreamChunk(content=payload.get("content", ""), tool_calls=payload.get("tool_calls"))


class RecordingClient(Client):
    def __init__(self) -> None:
        self.updates: list[Any] = []
        self.permission_calls: list[Any] = []
        self.permission_answer = "allow_once"

    async def session_update(self, session_id: str, update, **kwargs) -> None:
        self.updates.append(update)

    async def request_permission(self, session_id, tool_call, options, **kwargs) -> RequestPermissionResponse:
        from acp.schema import AllowedOutcome

        self.permission_calls.append(tool_call)
        if self.permission_answer == "deny":
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=self.permission_answer)
        )


class Wire:
    """一对已连接的 agent/client 连接。"""

    def __init__(
        self,
        conn: ClientSideConnection,
        client: RecordingClient,
        agent_conn: AgentSideConnection,
    ) -> None:
        self.conn = conn
        self.client = client
        self.agent_conn = agent_conn


async def _connect(tmp_path: Path, turns: list[dict[str, Any]]) -> Wire:
    agent_transport, client_transport = _pair()
    paths = AgentPaths(home=tmp_path / "home")
    paths.ensure_directories()

    agent = AcpAgent(workspace=tmp_path, paths=paths, llm=ScriptedLLM(turns))

    # listening=True 时两端各自在后台自动跑接收循环，无需手动 listen()
    agent_conn = AgentSideConnection(agent, agent_transport, listening=True)

    client = RecordingClient()
    client_conn = ClientSideConnection(client, client_transport, listening=True)

    return Wire(client_conn, client, agent_conn)


@pytest.mark.anyio
async def test_full_handshake_and_prompt_over_jsonrpc(tmp_path):
    wire = await _connect(tmp_path, [{"content": "hello over the wire"}])

    init = await wire.conn.initialize(protocol_version=PROTOCOL_VERSION)
    assert init.agent_info.name == "my-pi-agent"

    session = await wire.conn.new_session(cwd=str(tmp_path))
    assert session.session_id

    result = await wire.conn.prompt(
        session_id=session.session_id,
        prompt=[TextContentBlock(type="text", text="hi")],
    )
    assert result.stop_reason == "end_turn"

    texts = [u.content.text for u in wire.client.updates if isinstance(u, AgentMessageChunk)]
    assert "hello over the wire" in texts


@pytest.mark.anyio
async def test_tool_call_updates_cross_the_wire(tmp_path):
    (tmp_path / "note.txt").write_text("content", encoding="utf-8")
    wire = await _connect(
        tmp_path,
        [
            {"content": "", "tool_calls": [ToolCall(id="c1", name="read", args={"path": "note.txt"})]},
            {"content": "done"},
        ],
    )

    session = await wire.conn.new_session(cwd=str(tmp_path))
    await wire.conn.prompt(
        session_id=session.session_id,
        prompt=[TextContentBlock(type="text", text="read note.txt")],
    )

    starts = [u for u in wire.client.updates if isinstance(u, ToolCallStart)]
    progress = [u for u in wire.client.updates if isinstance(u, ToolCallProgress)]
    assert len(starts) == 1
    assert starts[0].tool_call_id == "c1"
    assert starts[0].kind == "read"
    assert any(u.status == "completed" for u in progress)


@pytest.mark.anyio
async def test_permission_request_reaches_client_and_denial_blocks_write(tmp_path):
    """端到端验证 ACP 反向审批：编辑器拒绝 → 写工具被 PermissionGate 拦截。"""
    wire = await _connect(
        tmp_path,
        [
            {
                "content": "",
                "tool_calls": [
                    ToolCall(
                        id="w1",
                        name="write",
                        args={"path": "blocked.txt", "content": "should not exist"},
                    )
                ],
            },
            {"content": "gave up"},
        ],
    )
    wire.client.permission_answer = "deny"

    session = await wire.conn.new_session(cwd=str(tmp_path))
    await wire.conn.prompt(
        session_id=session.session_id,
        prompt=[TextContentBlock(type="text", text="write blocked.txt")],
    )

    assert wire.client.permission_calls, "客户端应收到 session/request_permission 反向请求"
    assert wire.client.permission_calls[0].kind == "edit"
    assert not (tmp_path / "blocked.txt").exists(), "被拒绝的写操作不得落盘"


@pytest.mark.anyio
async def test_permission_approval_allows_write(tmp_path):
    wire = await _connect(
        tmp_path,
        [
            {
                "content": "",
                "tool_calls": [
                    ToolCall(id="w1", name="write", args={"path": "allowed.txt", "content": "written"})
                ],
            },
            {"content": "wrote it"},
        ],
    )
    wire.client.permission_answer = "allow_once"

    session = await wire.conn.new_session(cwd=str(tmp_path))
    await wire.conn.prompt(
        session_id=session.session_id,
        prompt=[TextContentBlock(type="text", text="write allowed.txt")],
    )

    assert wire.client.permission_calls
    assert (tmp_path / "allowed.txt").read_text(encoding="utf-8") == "written"


@pytest.mark.anyio
async def test_set_session_mode_over_the_wire(tmp_path):
    wire = await _connect(tmp_path, [{"content": "ok"}])
    session = await wire.conn.new_session(cwd=str(tmp_path))

    await wire.conn.set_session_mode(session_id=session.session_id, mode_id="yolo")
    # 未抛异常即说明协议往返成功；再发一轮确认会话仍可用
    result = await wire.conn.prompt(
        session_id=session.session_id,
        prompt=[TextContentBlock(type="text", text="hi")],
    )
    assert result.stop_reason == "end_turn"
