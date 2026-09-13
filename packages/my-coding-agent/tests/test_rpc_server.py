from __future__ import annotations

import io
import json
from pathlib import Path
import pytest

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
)
from my_agent_llm.models import Message, Response, StreamChunk
from my_coding_agent import CodingAgent, RpcServer, serialize_event


class FakeLLM:
    def __init__(self, model: str = "fake-model"):
        self.model = model

    async def achat(self, *a, **kw):
        return Response(content="ok", model=self.model)

    async def achat_stream(self, *a, **kw):
        yield StreamChunk(content="", metadata={"reasoning_content": "thinking..."})
        yield StreamChunk(content="answer text")


def test_serialize_all_events():
    msg = Message(role="assistant", content="hello")
    chunk = StreamChunk(content="delta", metadata={"reasoning_content": "think"})

    # AgentStart & AgentEnd
    start = serialize_event(AgentStart(system_prompt="sys", user_input="hi"))
    assert start["type"] == "agent_start"
    assert start["user_input"] == "hi"

    end = serialize_event(AgentEnd(messages=[msg], final_text="done", iterations=1, stop_reason="end_turn"))
    assert end["type"] == "agent_end"
    assert end["stop_reason"] == "end_turn"

    # TurnStart & TurnEnd
    t_start = serialize_event(TurnStart(iteration=1))
    assert t_start["type"] == "turn_start"
    assert t_start["iteration"] == 1

    t_end = serialize_event(TurnEnd())
    assert t_end["type"] == "turn_end"

    # Message Lifecycle
    m_start = serialize_event(MessageStart(message=msg))
    assert m_start["type"] == "message_start"
    assert m_start["message"]["role"] == "assistant"

    m_update = serialize_event(MessageUpdate(message=msg, chunk=chunk))
    assert m_update["type"] == "message_update"
    assert m_update["delta"] == "delta"
    assert m_update["reasoning_delta"] == "think"

    m_end = serialize_event(MessageEnd(message=msg))
    assert m_end["type"] == "message_end"

    # Tool Execution
    tool_start = serialize_event(ToolExecutionStart(tool_call_id="c1", tool_name="read", args={"path": "a.py"}))
    assert tool_start["type"] == "tool_execution_start"
    assert tool_start["toolCallId"] == "c1"
    assert tool_start["toolName"] == "read"

    tool_end = serialize_event(ToolExecutionEnd(tool_call_id="c1", tool_name="read", result="content", is_error=False))
    assert tool_end["type"] == "tool_execution_end"
    assert tool_end["toolCallId"] == "c1"
    assert tool_end["isError"] is False


@pytest.mark.anyio
async def test_rpc_server_initialize_and_prompt(tmp_path: Path):
    in_buf = io.StringIO()
    out_buf = io.StringIO()
    err_buf = io.StringIO()

    server = RpcServer(stdin=in_buf, stdout=out_buf, stderr=err_buf, llm=FakeLLM())

    # 1. Initialize
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"workspace": str(tmp_path), "model": "fake-model"},
    }
    resp = await server.handle_request(init_req)
    assert resp["id"] == 1
    assert resp["result"]["status"] == "ok"
    assert server.agent is not None
    assert server.agent.workspace == tmp_path.resolve()

    # Inject fake LLM to avoid real API
    server.agent.agent.llm = FakeLLM()  # type: ignore[assignment]

    # 2. Prompt Stream
    prompt_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "prompt",
        "params": {"text": "hello agent"},
    }
    resp2 = await server.handle_request(prompt_req)
    assert resp2["id"] == 2
    assert resp2["result"]["status"] == "completed"

    # 检查输出中是否有推送的事件 notifications
    output_lines = [json.loads(line) for line in out_buf.getvalue().splitlines() if line.strip()]
    event_types = [msg.get("params", {}).get("type") for msg in output_lines if msg.get("method") == "event"]
    assert "agent_start" in event_types
    assert "message_update" in event_types
    assert "agent_end" in event_types


@pytest.mark.anyio
async def test_rpc_server_steer_abort_and_shutdown(tmp_path: Path):
    in_buf = io.StringIO()
    out_buf = io.StringIO()
    server = RpcServer(stdin=in_buf, stdout=out_buf)
    server.agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    # Steer
    steer_req = {"jsonrpc": "2.0", "id": 10, "method": "steer", "params": {"message": "即时纠偏"}}
    steer_resp = await server.handle_request(steer_req)
    assert steer_resp["result"]["status"] == "ok"
    assert server.agent.agent.message_queue.has_steering()

    # Followup
    followup_req = {"jsonrpc": "2.0", "id": 11, "method": "followup", "params": {"message": "排队任务"}}
    followup_resp = await server.handle_request(followup_req)
    assert followup_resp["result"]["status"] == "ok"
    assert server.agent.agent.message_queue.has_followup()

    # Abort
    abort_req = {"jsonrpc": "2.0", "id": 12, "method": "abort", "params": {}}
    abort_resp = await server.handle_request(abort_req)
    assert abort_resp["result"]["status"] == "ok"

    # Shutdown
    shutdown_req = {"jsonrpc": "2.0", "id": 13, "method": "shutdown", "params": {}}
    shutdown_resp = await server.handle_request(shutdown_req)
    assert shutdown_resp["result"]["status"] == "ok"
    assert server.is_shutting_down is True


@pytest.mark.anyio
async def test_rpc_server_errors_and_edge_cases(tmp_path: Path):
    in_buf = io.StringIO()
    out_buf = io.StringIO()
    server = RpcServer(stdin=in_buf, stdout=out_buf)

    # 1. Uninitialized prompt error
    prompt_req = {"jsonrpc": "2.0", "id": 100, "method": "prompt", "params": {"text": "hi"}}
    resp = await server.handle_request(prompt_req)
    assert resp["error"]["code"] == -32001
    assert "Agent not initialized" in resp["error"]["message"]

    # 2. Unknown method error
    unknown_req = {"jsonrpc": "2.0", "id": 101, "method": "nonexistent", "params": {}}
    resp = await server.handle_request(unknown_req)
    assert resp["error"]["code"] == -32601
    assert "Method 'nonexistent' not found" in resp["error"]["message"]


@pytest.mark.anyio
async def test_rpc_server_run_forever(tmp_path: Path):
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(tmp_path)}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "abort", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}}),
    ]
    in_buf = io.StringIO("\n".join(lines) + "\n")
    out_buf = io.StringIO()
    server = RpcServer(stdin=in_buf, stdout=out_buf, llm=FakeLLM())

    await server.run_forever()

    output = out_buf.getvalue()
    assert '"id": 1' in output
    assert '"id": 2' in output
    assert '"id": 3' in output
    assert server.is_shutting_down is True
