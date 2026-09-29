"""AcpAgent 协议层单元测试。

通过注入脚本化 LLM 替身，端到端验证 ACP 会话生命周期与事件翻译，
不依赖任何真实模型凭据或网络。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from acp import PROTOCOL_VERSION
from acp.schema import AgentMessageChunk, TextContentBlock, ToolCallStart
from my_agent_llm.models import Response, StreamChunk, ToolCall

from my_acp_agent.agent import SESSION_MODES, AcpAgent
from my_coding_agent.paths import AgentPaths


class ScriptedLLM:
    """按轮次返回预置响应的 LLM 替身。"""

    def __init__(self, turns: list[dict[str, Any]] | None = None) -> None:
        self.turns = list(turns or [{"content": "hello from fake model"}])
        self.idx = 0

    def _next(self) -> dict[str, Any]:
        if self.idx < len(self.turns):
            payload = self.turns[self.idx]
            self.idx += 1
            return payload
        return {"content": "done"}

    async def achat(self, messages, tools=None, **kwargs) -> Response:
        payload = self._next()
        return Response(
            content=payload.get("content", ""),
            model="fake-acp-model",
            tool_calls=payload.get("tool_calls"),
        )

    async def achat_stream(self, messages, tools=None, **kwargs):
        payload = self._next()
        yield StreamChunk(content=payload.get("content", ""), tool_calls=payload.get("tool_calls"))


@pytest.fixture
def paths(tmp_path: Path) -> AgentPaths:
    p = AgentPaths(home=tmp_path / "home")
    p.ensure_directories()
    return p


def _make_agent(tmp_path: Path, paths: AgentPaths, turns=None) -> AcpAgent:
    return AcpAgent(workspace=tmp_path, paths=paths, llm=ScriptedLLM(turns))


def _attach_conn(agent: AcpAgent) -> AsyncMock:
    conn = AsyncMock()
    conn.session_update = AsyncMock()
    conn.request_permission = AsyncMock()
    agent.on_connect(conn)
    return conn


async def _new_session(agent: AcpAgent, tmp_path: Path) -> str:
    response = await agent.new_session(cwd=str(tmp_path))
    return response.session_id


# ── initialize ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_initialize_advertises_capabilities(tmp_path, paths):
    agent = _make_agent(tmp_path, paths)
    resp = await agent.initialize(protocol_version=PROTOCOL_VERSION)

    assert resp.protocol_version == PROTOCOL_VERSION
    assert resp.agent_capabilities.load_session is True
    assert resp.agent_info.name == "my-pi-agent"


# ── 会话生命周期 ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_new_session_returns_id_and_modes(tmp_path, paths):
    agent = _make_agent(tmp_path, paths)
    resp = await agent.new_session(cwd=str(tmp_path))

    assert resp.session_id
    assert resp.modes is not None
    assert resp.modes.current_mode_id == "review"
    assert {m.id for m in resp.modes.available_modes} == {m.id for m in SESSION_MODES}


@pytest.mark.anyio
async def test_new_session_persists_jsonl_file(tmp_path, paths):
    agent = _make_agent(tmp_path, paths)
    session_id = await _new_session(agent, tmp_path)

    session_file = paths.project_session_dir(tmp_path) / f"{session_id}.jsonl"
    assert session_file.is_file()


@pytest.mark.anyio
async def test_set_session_mode_updates_gate(tmp_path, paths):
    agent = _make_agent(tmp_path, paths)
    session_id = await _new_session(agent, tmp_path)

    await agent.set_session_mode(session_id=session_id, mode_id="yolo")
    runtime = agent._sessions[session_id]
    assert runtime.mode == "yolo"
    # yolo 在 PermissionGate 内部归一化为 autonomous
    assert runtime.agent.permission_gate.mode == "autonomous"


@pytest.mark.anyio
async def test_set_session_mode_rejects_unknown_mode(tmp_path, paths):
    from acp.exceptions import RequestError

    agent = _make_agent(tmp_path, paths)
    session_id = await _new_session(agent, tmp_path)

    with pytest.raises(RequestError):
        await agent.set_session_mode(session_id=session_id, mode_id="bogus")


@pytest.mark.anyio
async def test_close_session_removes_runtime(tmp_path, paths):
    agent = _make_agent(tmp_path, paths)
    session_id = await _new_session(agent, tmp_path)

    await agent.close_session(session_id=session_id)
    assert session_id not in agent._sessions


@pytest.mark.anyio
async def test_unknown_session_raises(tmp_path, paths):
    from acp.exceptions import RequestError

    agent = _make_agent(tmp_path, paths)
    with pytest.raises(RequestError):
        await agent.prompt(session_id="nope", prompt=[TextContentBlock(type="text", text="hi")])


@pytest.mark.anyio
async def test_list_sessions_reports_created_session(tmp_path, paths):
    agent = _make_agent(tmp_path, paths)
    session_id = await _new_session(agent, tmp_path)

    resp = await agent.list_sessions(cwd=str(tmp_path))
    assert session_id in [s.session_id for s in resp.sessions]


# ── prompt 与事件翻译 ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_prompt_streams_agent_message_chunk(tmp_path, paths):
    agent = _make_agent(tmp_path, paths, turns=[{"content": "hello world"}])
    conn = _attach_conn(agent)
    session_id = await _new_session(agent, tmp_path)

    resp = await agent.prompt(session_id=session_id, prompt=[TextContentBlock(type="text", text="hi")])

    assert resp.stop_reason == "end_turn"
    updates = [c.kwargs["update"] for c in conn.session_update.await_args_list]
    assert any(isinstance(u, AgentMessageChunk) and u.content.text == "hello world" for u in updates)


@pytest.mark.anyio
async def test_prompt_emits_tool_call_lifecycle(tmp_path, paths):
    (tmp_path / "sample.txt").write_text("body", encoding="utf-8")
    agent = _make_agent(
        tmp_path,
        paths,
        turns=[
            {"content": "", "tool_calls": [ToolCall(id="c1", name="read", args={"path": "sample.txt"})]},
            {"content": "read it"},
        ],
    )
    conn = _attach_conn(agent)
    session_id = await _new_session(agent, tmp_path)

    await agent.prompt(session_id=session_id, prompt=[TextContentBlock(type="text", text="read sample.txt")])

    updates = [c.kwargs["update"] for c in conn.session_update.await_args_list]
    starts = [u for u in updates if isinstance(u, ToolCallStart)]
    assert len(starts) == 1
    assert starts[0].tool_call_id == "c1"
    assert starts[0].kind == "read"
    # 工具结束后应有一条 completed 的 tool_call_update
    assert any(getattr(u, "status", None) == "completed" for u in updates)


@pytest.mark.anyio
async def test_prompt_empty_text_is_noop(tmp_path, paths):
    agent = _make_agent(tmp_path, paths)
    conn = _attach_conn(agent)
    session_id = await _new_session(agent, tmp_path)

    resp = await agent.prompt(session_id=session_id, prompt=[])
    assert resp.stop_reason == "end_turn"
    conn.session_update.assert_not_awaited()


@pytest.mark.anyio
async def test_prompt_without_connection_does_not_crash(tmp_path, paths):
    """连接尚未建立时（on_connect 未触发）事件被静默丢弃，不应抛异常。"""
    agent = _make_agent(tmp_path, paths, turns=[{"content": "hi"}])
    session_id = await _new_session(agent, tmp_path)

    resp = await agent.prompt(session_id=session_id, prompt=[TextContentBlock(type="text", text="hi")])
    assert resp.stop_reason == "end_turn"


@pytest.mark.anyio
async def test_cancel_marks_session_cancelled(tmp_path, paths):
    agent = _make_agent(tmp_path, paths)
    _attach_conn(agent)
    session_id = await _new_session(agent, tmp_path)

    await agent.cancel(session_id=session_id)
    assert agent._sessions[session_id].cancelled is True


@pytest.mark.anyio
async def test_cancel_unknown_session_is_noop(tmp_path, paths):
    agent = _make_agent(tmp_path, paths)
    await agent.cancel(session_id="missing")


# ── 会话恢复 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_load_session_replays_history(tmp_path, paths):
    agent = _make_agent(tmp_path, paths, turns=[{"content": "first answer"}])
    _attach_conn(agent)
    session_id = await _new_session(agent, tmp_path)
    await agent.prompt(session_id=session_id, prompt=[TextContentBlock(type="text", text="first question")])
    await agent.close_session(session_id=session_id)

    # 换一个全新 agent 实例，模拟编辑器重启后恢复会话
    fresh = _make_agent(tmp_path, paths)
    fresh_conn = _attach_conn(fresh)
    resp = await fresh.load_session(cwd=str(tmp_path), session_id=session_id)

    assert resp is not None
    updates = [c.kwargs["update"] for c in fresh_conn.session_update.await_args_list]
    assert updates, "load_session 应回放历史消息"


@pytest.mark.anyio
async def test_load_session_missing_raises(tmp_path, paths):
    from acp.exceptions import RequestError

    agent = _make_agent(tmp_path, paths)
    with pytest.raises(RequestError):
        await agent.load_session(cwd=str(tmp_path), session_id="does-not-exist")
